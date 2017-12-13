#!/usr/bin/env python

import configparser
import requests
import boto3
import pprint
import sys
import os
import datetime

import logging
logger = logging.getLogger(__name__)


class GrafanaAlerts:

    def __init__(self, keyword, overwrite):
        self.keyword = keyword
        self.overwrite = overwrite

        dirname = os.path.dirname(os.path.abspath(__file__))

        parser = configparser.SafeConfigParser(delimiters=('='))
        parser.optionxform = lambda option: option
        config_file = os.path.join(dirname, 'config.ini')
        parser.read(config_file)

        self.grafana_host = parser.get('grafana', 'host')
        self.grafana_auth = parser.get('grafana', 'auth')

        template_file = os.path.join(dirname, parser.get(self.keyword, 'template'))
        self.template = open(template_file, 'r').read()

        self.query_name = parser.get(self.keyword, 'query_name')

        self.filters = []
        for name in parser.options(self.keyword + '_Filters'):
            self.filters.append({
                'Name': str(name),
                'Values': [str(parser.get(self.keyword + '_Filters', name))]
            })

        aws_access_key = parser.get('aws', 'access_key')
        aws_secret_key = parser.get('aws', 'secret_key')
        aws_region = parser.get('aws', 'region')
        self.aws_ec2 = boto3.client('ec2', region_name=aws_region, aws_access_key_id=aws_access_key, aws_secret_access_key=aws_secret_key)

    def get_ec2_list(self):
        r = self.aws_ec2.describe_instances(Filters=self.filters)
        if r['ResponseMetadata']['HTTPStatusCode'] != 200:
            pprint.pprint(r)
            logger.error('get_ec2_list failed, %s', r)
            return False, []
        ec2_list = []
        for rese in r[u'Reservations']:
            for inst in rese[u'Instances']:
                # only record the EC2 instances created after 5 mins
                # in order to avoid the "no data" alerts while the EC2 instances were just created and had no metrics collected
                if inst[u'LaunchTime'] > datetime.datetime.now(inst[u'LaunchTime'].tzinfo) - datetime.timedelta(minutes=5):
                    continue
                ec2_list.append({
                    'name': filter(lambda tag: tag[u'Key'] == 'Name', inst[u'Tags'])[0][u'Value'],
                    'region': inst[u'Placement'][u'AvailabilityZone'],
                    'private_ip': inst[u'PrivateIpAddress'],
                    'public_ip': inst[u'PublicIpAddress'],
                    'instance_type': inst[u'InstanceType'],
                    'life_cycle': inst[u'InstanceLifecycle'] if inst.has_key(u'InstanceLifecycle') else 'normal'
                })
        return True, ec2_list

    def get_dashboard_list(self):
        """
        The output format:

        [{u'id': 32,
          u'isStarred': False,
          u'tags': [u'EC2K8SAlerts', u'ec2', u'monitor', u'visearch'],
          u'title': u'EC2 Monitor: [SG] [nodes.sg0.apik8s.visenze.com] [normal] [c4.xlarge] [54.254.231.131/10.0.69.209]',
          u'type': u'dash-db',
          u'uri': u'db/ec2-monitor-sg-nodes-sg0-apik8s-visenze-com-normal-c4-xlarge-54-254-231-131-10-0-69-209'}]
        """
        grafana_endpoint_dashboard_list = '%s/api/search?tag=%s' % (self.grafana_host, self.keyword)
        r = requests.get(grafana_endpoint_dashboard_list, headers={
                'Authorization': self.grafana_auth
            })
        print "get_dashboard response, status_code:", r.status_code
        if r.status_code == 200:
            return True, r.json()
        else:
            logger.error('get_dashboard failed, %s', r.json())
            return False, []

    def del_dashboard(self, db):
        grafana_endpoint_del_dashboard = '%s/api/dashboards/%s' % (self.grafana_host, db)
        r = requests.delete(grafana_endpoint_del_dashboard, headers={
                'Authorization': self.grafana_auth
            })
        print "del_dashboard response, status_code:", r.status_code
        pprint.pprint(r.json())
        logger.info('del_dashboard, %s', r.json())
        return r.status_code == 200

    def new_dashboard(self, setting):
        grafana_endpoint_new_dashboard = '%s/api/dashboards/db' % self.grafana_host
        r = requests.post(grafana_endpoint_new_dashboard, data=setting, headers={
                'Authorization': self.grafana_auth,
                'Content-Type': 'application/json'
            })
        print "new_dashboard response, status_code:", r.status_code
        pprint.pprint(r.json())
        logger.info('new_dashboard, %s', r.json())
        return r.status_code == 200 and r.json()['status'] == 'success'

    def del_expired_dashboard(self, dashboard_list):
        for dashboard in dashboard_list:
            self.del_dashboard(str(dashboard[u'uri']))

    def get_expired_dashboard(self, dashboard_list, ec2_list):
        expired = []
        for dashboard in dashboard_list:
            found = False
            for ec2 in ec2_list:
                if ec2['public_ip'] in str(dashboard[u'title']):
                    found = True
                    break
            if not found:
                expired.append(dashboard)
        return expired

    def get_missing_ec2(self, dashboard_list, ec2_list):
        missing = []
        for ec2 in ec2_list:
            found = False
            for dashboard in dashboard_list:
                if ec2['public_ip'] in str(dashboard[u'title']):
                    found = True
                    break
            if not found:
                missing.append(ec2)
        return missing

    def get_dashboard_setting(self, ec2):
        return self.template.replace('<REGION>', ec2['region']) \
                            .replace('<NAME>', ec2['name']) \
                            .replace('<PRIVATEIP>', ec2['private_ip']) \
                            .replace('<PUBLICIP>', ec2['public_ip']) \
                            .replace('<INSTANCETYPE>', ec2['instance_type']) \
                            .replace('<LIFECYCLE>', ec2['life_cycle']) \
                            .replace('<NODENAME>', ec2['private_ip'].replace('.', '-')) \
                            .replace('<KEYWORD>', self.keyword)

    def add_missing_ec2(self, ec2_list):
        for ec2 in ec2_list:
            setting = self.get_dashboard_setting(ec2)
            self.new_dashboard(setting)

    def run(self):
        ret, ec2_list = self.get_ec2_list()
        if not ret:
            return

        ret, dashboard_list = self.get_dashboard_list()
        if not ret:
            return

        expired_dashboard = self.get_expired_dashboard(dashboard_list, ec2_list)
        self.del_expired_dashboard(expired_dashboard)

        if self.overwrite:
            self.add_missing_ec2(ec2_list)
        else:
            missing_ec2 = self.get_missing_ec2(dashboard_list, ec2_list)
            self.add_missing_ec2(missing_ec2)


def load_region_alerts(rewrite):
    c = GrafanaAlerts('EC2RegionAlerts', rewrite)
    c.run()

if __name__ == '__main__':
    rewrite = True if len(sys.argv) >= 2 and (sys.argv[1] == 'True' or sys.argv[1] == 'true') else False
    load_region_alerts(rewrite)

