from aws_cdk import (
    Stack,
    aws_cloudwatch as cloudwatch,
    aws_cloudwatch_actions as cw_actions,
    aws_sns as sns,
    aws_sns_subscriptions as subscriptions,
    Duration
)

from constructs import Construct
from infra.compute_stack import ComputeStack
from infra.msk_stack import MskStack
from infra.data_stack import DataStack

class MonitoringStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, compute_stack: ComputeStack, msk_stack: MskStack, data_stack: DataStack, alert_email: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        alert_topic = sns.Topic(
            self,
            "AlertTopic",
            topic_name="scorestream-alerts",
            display_name="Scorestream Alerts"
        )

        alert_topic.add_subscription(subscriptions.EmailSubscription(alert_email))

        alarm_action = cw_actions.SnsAction(alert_topic)

        producer_task_count = cloudwatch.Metric(
            namespace="ECS/ContainerInsights",
            metric_name="RunningTaskCount",
            dimensions_map={
                "ClusterName": "scorestream",
                "ServiceName": "scorestream-producer"
            },
            statistic="Minimum",
            period=Duration.minutes(5)
        )

        producer_down_alarm = cloudwatch.Alarm(
            self,
            "ProducerDownAlarm",
            metric=producer_task_count,
            threshold=1,
            evaluation_periods=2,
            datapoints_to_alarm=2,
            comparison_operator=cloudwatch.ComparisonOperator.LESS_THAN_THRESHOLD,
            alarm_name="scorestream-producer-down",
            alarm_description="Producer ECS task count is below 1 -- Pipleline stopped!",
            treat_missing_data=cloudwatch.TreatMissingData.BREACHING
        )

        producer_down_alarm.add_alarm_action(alarm_action)
        producer_down_alarm.add_ok_action(alarm_action)

        api_task_count = cloudwatch.Metric(
            namespace="ECS/ContainerInsights",
            metric_name="RunningTaskCount",
            dimensions_map={
                "ClusterName": "scorestream",
                "ServiceName": "scorestream-api",
            },
            statistic="Minimum",
            period=Duration.minutes(5),
        )

        api_down_alarm = cloudwatch.Alarm(
            self, "ApiDownAlarm",
            metric=api_task_count,
            threshold=1,
            comparison_operator=cloudwatch.ComparisonOperator.LESS_THAN_THRESHOLD,
            evaluation_periods=2,
            datapoints_to_alarm=2,
            alarm_name="scorestream-api-down",
            alarm_description="API ECS task count dropped below 1",
            treat_missing_data=cloudwatch.TreatMissingData.BREACHING,
        )
        api_down_alarm.add_alarm_action(alarm_action)
        api_down_alarm.add_ok_action(alarm_action)


        alb_5xx = cloudwatch.Metric(
            namespace="AWS/ApplicationELB",
            metric_name="HTTPCode_Target_5XX_Count",
            dimensions_map={
                "LoadBalancer": compute_stack.alb_dns_name
            },
            statistic="Sum",
            period=Duration.minutes(5),
        )

        alb_5xx_alarm = cloudwatch.Alarm(
            self,
            "Alb5xxAlarm",
            metric=alb_5xx,
            threshold=10,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
            evaluation_periods=2,
            datapoints_to_alarm=2,
            alarm_name="scorestream-alb-5xx",
            alarm_description="ALB returning elevated 5xx errors",
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING
        )
        alb_5xx_alarm.add_alarm_action(alarm_action)

        alb_latency = cloudwatch.Metric(
            namespace="AWS/ApplicationELB",
            metric_name="TargetResponseTime",
            dimensions_map={
                "LoadBalancer": compute_stack.alb_dns_name
            },
            statistic="p99",
            period=Duration.minutes(5),            
        )

        alb_latency_alarm = cloudwatch.Alarm(
            self,
            "AlbLatencyAlarm",
            metric=alb_latency,
            threshold=5,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
            evaluation_periods=3,
            datapoints_to_alarm=3,
            alarm_name="scorestream-api-latency",
            alarm_description="API p99 response time is above 5 seconds",
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING
        )
        alb_latency_alarm.add_alarm_action(alarm_action)

        msk_lag = cloudwatch.Metric(
            namespace="AWS/Kafka",
            metric_name="ConsumerLag",
            dimensions_map={
                "Cluster Name": "scorestream-kafka",
                "Consumer Group": "scorestream-glue",
                "Topic": "sports.live.scores"
            },
            statistic="Maximum",
            period=Duration.minutes(5),
        )

        msk_lag_alarm = cloudwatch.Alarm(
            self,
            "MskLagAlarm",
            metric=msk_lag,
            threshold=300,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
            evaluation_periods=3,
            datapoints_to_alarm=3,
            alarm_name="scorestream-msk-lag",
            alarm_description="MSK consumer lag is above 5 minutes -- Glue job is falling behind or maybe stopped!",
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING
        )
        msk_lag_alarm.add_alarm_action(alarm_action)

        rds_connections = cloudwatch.Metric(
            namespace="AWS/RDS",
            metric_name="DatabaseConnections",
            dimensions_map={
                "DBInstanceIdentifier": "scorestream-rds"
            },
            statistic="Maximum",
            period=Duration.minutes(5),
        )

        rds_connections_alarm = cloudwatch.Alarm(
            self,
            "RdsConnectionsAlarm",
            metric=rds_connections,
            threshold=80,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
            evaluation_periods=2,
            datapoints_to_alarm=2,
            alarm_name="scorestream-rds-connections",
            alarm_description="RDS connections count approaching limit",
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING
        )
        rds_connections_alarm.add_alarm_action(alarm_action)

        rds_cpu = cloudwatch.Metric(
            namespace="AWS/RDS",
            metric_name="CPUUtilization",
            dimensions_map={
                "DBInstanceIdentifier": "scorestream-rds"
            },
            statistic="Average",
            period=Duration.minutes(5),
        )

        rds_cpu_alarm = cloudwatch.Alarm(
            self,
            "RdsCpuAlarm",
            metric=rds_cpu,
            threshold=80,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
            evaluation_periods=3,
            datapoints_to_alarm=3,
            alarm_name="scorestream-rds-cpu",
            alarm_description="RDS CPU utilization approaching 80% -- queries may be slow",
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING
        )
        rds_cpu_alarm.add_alarm_action(alarm_action)

        billing_alarm = cloudwatch.Alarm(
            self,
            "BillingAlarm",
            metric=cloudwatch.Metric(
                namespace="AWS/Billing",
                metric_name="EstimatedCharges",
                dimensions_map={
                    "Currency": "USD"
                },
                statistic="Maximum",
                period=Duration.hours(6),
            ),
            threshold=50,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
            evaluation_periods=1,
            alarm_name="scorestream-billing",
            alarm_description="Estimated AWS charges have exceeded $50",
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING
        )
        billing_alarm.add_alarm_action(alarm_action)

        dashboard = cloudwatch.Dashboard(
            self, "ScoreStreamDashboard",
            dashboard_name="ScoreStream",
        )

        dashboard.add_widgets(
            # Row 1 — Pipeline health
            cloudwatch.GraphWidget(
                title="Producer Running Tasks",
                left=[producer_task_count],
                width=8,
                height=6,
            ),
            cloudwatch.GraphWidget(
                title="MSK Consumer Lag",
                left=[msk_lag],
                width=8,
                height=6,
            ),
            cloudwatch.GraphWidget(
                title="API Running Tasks",
                left=[api_task_count],
                width=8,
                height=6,
            ),
        )

        dashboard.add_widgets(
            # Row 2 — Service health
            cloudwatch.GraphWidget(
                title="ALB 5xx Errors",
                left=[alb_5xx],
                width=8,
                height=6,
            ),
            cloudwatch.GraphWidget(
                title="API Response Time (p99)",
                left=[alb_latency],
                width=8,
                height=6,
            ),
            cloudwatch.GraphWidget(
                title="RDS Connections",
                left=[rds_connections],
                width=8,
                height=6,
            ),
        )

        dashboard.add_widgets(
            # Row 3 — Resource utilization
            cloudwatch.GraphWidget(
                title="RDS CPU",
                left=[rds_cpu],
                width=12,
                height=6,
            ),
            cloudwatch.AlarmStatusWidget(
                title="Alarm Summary",
                alarms=[
                    producer_down_alarm,
                    api_down_alarm,
                    alb_5xx_alarm,
                    alb_latency_alarm,
                    msk_lag_alarm,
                    rds_connections_alarm,
                    rds_cpu_alarm,
                ],
                width=12,
                height=6,
            ),
        )