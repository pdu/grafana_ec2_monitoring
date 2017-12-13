At [ViSenze](https://www.visenze.com/), we plan to use [Grafana](https://grafana.com/) to monitor the AWS/EC2 instances. 

Currently, Grafana doesn't support to trigger the alerts by the series in the same graph. It means the if server A pass CPU 90% threshold then trigger alert, before the alert resolve if server B also pass CPU 90% threshold, the alert will not trigger again. But we definitely want the alerts for server A and server B can be triggered and resolved separately. 

It means we have to configure different graphs for each server, it's impossible for us to do it manually because we have hundreds of EC2 instances and the instances are created and destoryed all the time. Then we write some scripts to run it automatically, it works well and we share it as it may be useful for other [Grafana users](https://github.com/grafana/grafana/issues/6041#issuecomment-350218119).

# Configuration

## config.ini

    [grafana]
    host = YOUR_GRAFANA_HOST
    auth = YOUR_GRAFANA_AUTH
    
    [EC2RegionAlerts]
    template = templates/ec2_region_alerts.json
                
    [EC2RegionAlerts_Filters]
    instance-state-name = running
    tag:Project = ViSearch
    tag:Component = region_server
    
    [aws]
    access_key = YOUR_AWS_ACCESS_KEY
    secret_key = YOUR_AWS_SECRET_KEY
    region = ap-southeast-1

## template

 - The template file is just for reference, you'd better configure the dashboard for one EC2 instance according to your own requirements, and export it as a template.
 - The keywords in the template file, the program will replace the keywords with the related values of each EC2 instance:
	 - \<REGION\>
	 - \<NAME\>
	 - \<LIFECYCLE\>
	 - \<INSTANCETYPE\>
	 - \<PUBLICIP\>
	 - \<PRIVATEIP\>
	 - \<NODENAME\>
	 - \<KEYWORD\>
		 - The program use the \<KEYWORD\> as the dashboard tag, in order to get the dashboard list by filtering by the tag.
		 - In this example, **EC2RegionAlerts** is the keyword.

# How to use it

Run the script every minute as a cron job.

## internal logic

 - Get the EC2 instance list from AWS
 - Get the dashboard list from Grafana
 - Create dashboard for the new EC2 instances
	 - Generate the dashboard setting based on the template
 - Delete dashboard for the destroyed EC2 instances

## alerts setting

 - Send email when CPU avg usage > 90% in the last 5 mins
 - Send pagerduty when CPU avg usage > 90% in the last 30 mins
 - Send email when Memory avg usage > 90% in the last 5 mins
 - Send pagerduty when Memory avg usage > 90% in the last 30 mins
 - Send pagerduty when Disk avg usage > 90% in the last 5 mins
 - Send email when Network avg RX rate > 60MB/s in the last 5 mins
 - Send email when Network avg TX rate > 60MB/s in the last 5 mins
 - Send email when Network avg RX error > 0 in the last 5 mins
 - Send email when Network avg TX error > 0 in the last 5 mins

# Troubleshooting

## can not get the full list of dashboard from Grafana

If you have more than 1000 dashboards in Grafana, you need to pay attention to [this](https://github.com/grafana/grafana/blob/05d43999dc83c2adc5bda27eb8e41e0b762c35ea/pkg/api/search.go#L16).

    func Search(c *middleware.Context) {
		query := c.Query("query")
		tags := c.QueryStrings("tag")
		starred := c.Query("starred")
		limit := c.QueryInt("limit")
	
		if limit == 0 {
			limit = 1000
		}
	
		dbids := make([]int, 0)
		for _, id := range c.QueryStrings("dashboardIds") {
			dashboardId, err := strconv.Atoi(id)
			if err == nil {
				dbids = append(dbids, dashboardId)
			}
		}
	
		searchQuery := search.Query{
			Title:        query,
			Tags:         tags,
			UserId:       c.UserId,
			Limit:        limit,
			IsStarred:    starred == "true",
			OrgId:        c.OrgId,
			DashboardIds: dbids,
		}
	
		err := bus.Dispatch(&searchQuery)
		if err != nil {
			c.JsonApiErr(500, "Search failed", err)
			return
		}
	
		c.TimeRequest(metrics.M_Api_Dashboard_Search)
		c.JSON(200, searchQuery.Result)
	}
