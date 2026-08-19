from aws_cdk import (
    Stack,
    aws_ecs as ecs,
    aws_iam as iam,
    aws_ecr as ecr,
    aws_logs as logs,
    aws_ec2 as ec2,
    aws_glue as glue,
    aws_elasticloadbalancingv2 as elbv2,
    aws_certificatemanager as acm,
    aws_scheduler as scheduler,
    aws_s3_deployment as s3deploy,
    aws_scheduler_targets as targets,
    Duration,
    RemovalPolicy,
    Fn
)

from constructs import Construct
from infra.network_stack import NetworkStack
from infra.data_stack import DataStack
from infra.msk_stack import MskStack
import json

class ComputeStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, network: NetworkStack, data: DataStack, msk: MskStack, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.cluster = ecs.Cluster(
            self,
            "ScoreStreamCluster",
            cluster_name="scorestream",
            vpc=network.vpc,
            container_insights=True
        )

        producer_task_role = iam.Role(
            self,
            "ProducerTaskRole",
            assumed_by=iam.ServicePrincipal("ecs-tasks.amazonaws.com"),
            description="IAM role for ScoreStream producer ECS task",
        )

        data.grant_secrets_read(producer_task_role)

        cluster_arn = msk.cluster.cluster_arn

        prefix = Fn.select(0, Fn.split(":cluster/", cluster_arn))
        suffix = Fn.select(1, Fn.split(":cluster/", cluster_arn))

        topic = Fn.join("", [prefix, ":topic/", suffix, "/*"])
        group = Fn.join("", [prefix, ":group/", suffix, "/*/*"])
        
        producer_task_role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "kafka-cluster:Connect",
                    "kafka-cluster:AlterCluster",
                    "kafka-cluster:DescribeCluster",
                ],
                resources=[msk.cluster.cluster_arn],
            )
        )

        producer_task_role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "kafka-cluster:DescribeTopic",
                    "kafka-cluster:WriteData",
                    "kafka-cluster:CreateTopic",
                    "kafka-cluster:ReadData",
                    "kafka-cluster:AlterTopic",
                    "kafka-cluster:DeleteTopic",
                ],
                resources=[topic],
            )
        )

        producer_task_role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "kafka-cluster:DescribeGroup",
                    "kafka-cluster:AlterGroup",
                ],
                resources=[group],
            )
        )

        producer_execution_role = iam.Role(
            self,
            "ProducerExecutionRole",
            assumed_by=iam.ServicePrincipal("ecs-tasks.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name("service-role/AmazonECSTaskExecutionRolePolicy")
            ]
        )

        data.grant_secrets_read(producer_execution_role)

        producer_task = ecs.FargateTaskDefinition(
            self,
            "ProducerTask",
            task_role=producer_task_role,
            execution_role=producer_execution_role,
            cpu=256,
            memory_limit_mib=512
        )

        producer_repo = ecr.Repository.from_repository_name(
            self,
            "ProducerRepo",
            repository_name="scorestream/producer"
        )

        producer_repo.grant_pull(producer_execution_role)

        producer_log_group = logs.LogGroup(
            self,
            "ProducerLogs",
            log_group_name="/scorestream/producer",
            retention=logs.RetentionDays.ONE_WEEK,
            removal_policy=RemovalPolicy.DESTROY
        )
        producer_log_group.grant_write(producer_execution_role)

        producer_task.add_container(
            "ProducerContainer",
            image=ecs.ContainerImage.from_ecr_repository(producer_repo, tag="latest"),
            environment={
                "KAFKA_BOOTSTRAP_SERVERS": msk.bootstrap_brokers_iam,
                "POLL_INTERVAL_SECONDS": "15",
                "KAFKA_TOPIC_SCORES": "sports.live.scores",
                "KAFKA_TOPIC_STANDINGS": "sports.standings",
                "AWS_DEFAULT_REGION": "us-east-1"
            },
            secrets={
                "ANTHROPIC_API_KEY": ecs.Secret.from_secrets_manager(network.secret_anthropic),
                "FOOTBALL_DATA_API_KEY": ecs.Secret.from_secrets_manager(network.secret_football_data),
                "DB_HOST": ecs.Secret.from_secrets_manager(data.secret_rds, field="host"),
                "DB_PORT": ecs.Secret.from_secrets_manager(data.secret_rds, field="port"),
                "DB_USER": ecs.Secret.from_secrets_manager(data.secret_rds, field="username"),
                "DB_PASSWORD": ecs.Secret.from_secrets_manager(data.secret_rds, field="password"),
                "DB_NAME": ecs.Secret.from_secrets_manager(data.secret_rds, field="dbname"),
                "PROXY_USERNAME": ecs.Secret.from_secrets_manager(network.secret_proxy, field="username"),
                "PROXY_PASSWORD": ecs.Secret.from_secrets_manager(network.secret_proxy, field="password"),
                "PROXY_HOST": ecs.Secret.from_secrets_manager(network.secret_proxy, field="host"),
                "PROXY_PORT": ecs.Secret.from_secrets_manager(network.secret_proxy, field="port"),
            },
            logging=ecs.LogDrivers.aws_logs(
                stream_prefix="producer",
                log_group=producer_log_group
            )
        )

        producer_service = ecs.FargateService(
            self,
            "ProducerService",
            cluster=self.cluster,
            task_definition=producer_task,
            desired_count=1,
            service_name="scorestream-producer",
            assign_public_ip=False,
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS),
            security_groups=[network.sg_producer],
            enable_execute_command=True
        )

        producer_task_role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "ssmmessages:CreateControlChannel",
                    "ssmmessages:CreateDataChannel",
                    "ssmmessages:OpenControlChannel",
                    "ssmmessages:OpenDataChannel"
                ],
                resources=["*"]
            )
        )

        s3deploy.BucketDeployment(
            self,
            "GlueScriptsDeployment",
            sources=[s3deploy.Source.asset("../spark/", exclude=["**", "!streaming_aws.py"])],
            destination_bucket=data.glue_bucket,
            destination_key_prefix="scripts",
        )

        glue_role = iam.Role(
            self,
            "GlueRole",
            assumed_by=iam.ServicePrincipal("glue.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name("service-role/AWSGlueServiceRole")
            ],
            description="IAM role for ScoreStream Glue streaming jobs"
        )

        data.grant_secrets_read(glue_role)
        data.grant_glue_bucket_access(glue_role)

        glue_role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "kafka-cluster:Connect",
                    "kafka-cluster:DescribeCluster",
                    "kafka-cluster:AlterCluster",
                ],
                resources=[msk.cluster.cluster_arn],
            )
        )

        glue_role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "kafka-cluster:ReadData",
                    "kafka-cluster:WriteData",
                    "kafka-cluster:DescribeTopic",
                    "kafka-cluster:CreateTopic",
                    "kafka-cluster:AlterTopic",
                ],
                resources=[f"arn:aws:kafka:us-east-1:{self.account}:topic/*"],
            )
        )

        glue_role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "kafka-cluster:AlterGroup",
                    "kafka-cluster:DescribeGroup",
                ],
                resources=[f"arn:aws:kafka:us-east-1:{self.account}:group/*"],
            )
        )

        glue_role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "ec2:CreateNetworkInterface",
                    "ec2:DeleteNetworkInterface",
                    "ec2:DescribeNetworkInterfaces",
                    "ec2:DescribeSecurityGroups",
                    "ec2:DescribeSubnets",
                    "ec2:DescribeVpcs",
                ],
                resources=["*"],
            )
        )

        glue_connection = glue.CfnConnection(
            self,
            "GlueConnection",
            catalog_id=self.account,
            connection_input=glue.CfnConnection.ConnectionInputProperty(
                name="scorestream-vpc-connection",
                connection_type="NETWORK",
                physical_connection_requirements=glue.CfnConnection.PhysicalConnectionRequirementsProperty(
                    availability_zone=network.vpc.private_subnets[0].availability_zone,
                    security_group_id_list=[network.sg_glue.security_group_id],
                    subnet_id=network.vpc.private_subnets[0].subnet_id
                )
            )
        )

        glue_job = glue.CfnJob(
            self, "ScoreStreamGlueJob",
            name="scorestream-streaming",
            role=glue_role.role_arn,
            command=glue.CfnJob.JobCommandProperty(
                name="gluestreaming",
                python_version="3",
                script_location=f"s3://scorestream-glue-{self.account}/scripts/streaming_job.py",
            ),
            glue_version="4.0",
            worker_type="G.1X",
            number_of_workers=2,
            connections=glue.CfnJob.ConnectionsListProperty(
                connections=["scorestream-vpc-connection"]
            ),
            default_arguments={
                "--KAFKA_BOOTSTRAP_SERVERS": msk.bootstrap_brokers_iam,
                "--CHECKPOINT_BUCKET":       f"scorestream-glue-{self.account}",
                "--AWS_REGION":              "us-east-1",
                "--REDIS_HOST":              data.redis_endpoint,
                "--REDIS_PORT":              data.redis_port,
                "--RDS_SECRET_NAME":         "scorestream/rds-credentials",  # ← add this
                "--enable-continuous-cloudwatch-log": "true",
                "--enable-metrics":          "true",
                "--enable-spark-ui":         "true",
                "--spark-event-logs-path":   f"s3://scorestream-glue-{self.account}/spark-logs/",
                "--job-language":            "python",
                "--additional-python-modules": "redis==5.0.1,psycopg2-binary==2.9.6",
            },
            execution_property=glue.CfnJob.ExecutionPropertyProperty(
                max_concurrent_runs=1,
            ),
        )

        self.alb = elbv2.ApplicationLoadBalancer(
            self,
            "ScoreStreamALB",
            vpc=network.vpc,
            internet_facing=True,
            security_group=network.sg_alb,
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PUBLIC),
            load_balancer_name="scorestream-alb"
        )

        self.alb.set_attribute("idle_timeout.timeout_seconds", "4000")
        self.alb_dns_name = self.alb.load_balancer_dns_name

        api_task_role = iam.Role(
            self,
            "ApiTaskRole",
            assumed_by=iam.ServicePrincipal("ecs-tasks.amazonaws.com"),
            description="IAM role for ScoreStream API ECS task",
        )

        data.grant_secrets_read(api_task_role)

        api_task_role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "ssmmessages:CreateControlChannel",
                    "ssmmessages:CreateDataChannel",
                    "ssmmessages:OpenControlChannel",
                    "ssmmessages:OpenDataChannel"
                ],
                resources=["*"]
            )
        )

        api_task_role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "cloudwatch:DescribeAlarms",
                ],
                resources=["*"]
            )
        )

        api_execution_role = iam.Role(
            self,
            "ApiExecutionRole",
            assumed_by=iam.ServicePrincipal("ecs-tasks.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name("service-role/AmazonECSTaskExecutionRolePolicy")
            ]
        )

        data.grant_secrets_read(api_execution_role)

        api_task = ecs.FargateTaskDefinition(
            self,
            "ApiTask",
            task_role=api_task_role,
            execution_role=api_execution_role,
            cpu=512,
            memory_limit_mib=1024
        )

        api_repo = ecr.Repository.from_repository_name(
            self,
            "ApiRepo",
            repository_name="scorestream/api"
        )

        api_log_group = logs.LogGroup(
            self,
            "ApiLogs",
            log_group_name="/scorestream/api",
            retention=logs.RetentionDays.ONE_WEEK,
            removal_policy=RemovalPolicy.DESTROY
        )

        api_task.add_container(
            "ApiContainer",
            image=ecs.ContainerImage.from_ecr_repository(api_repo, tag="latest"),
            port_mappings=[ecs.PortMapping(container_port=8000, protocol=ecs.Protocol.TCP)],
            environment={
                "AWS_DEFAULT_REGION": "us-east-1",
                "REDIS_HOST": data.redis_endpoint,
                "REDIS_PORT": data.redis_port,
                "ALLOWED_ORIGINS": "https://d1xoiixjmue879.cloudfront.net/"
            },
            secrets={
                "DB_HOST": ecs.Secret.from_secrets_manager(data.secret_rds, field="host"),
                "DB_PORT": ecs.Secret.from_secrets_manager(data.secret_rds, field="port"),
                "DB_USER": ecs.Secret.from_secrets_manager(data.secret_rds, field="username"),
                "DB_PASSWORD": ecs.Secret.from_secrets_manager(data.secret_rds, field="password"),
                "DB_NAME": ecs.Secret.from_secrets_manager(data.secret_rds, field="dbname"),
                "ANTHROPIC_API_KEY": ecs.Secret.from_secrets_manager(network.secret_anthropic),
            },
            logging=ecs.LogDrivers.aws_logs(
                stream_prefix="api",
                log_group=api_log_group
            )
        )

        http_listener = self.alb.add_listener(
            "HttpListener",
            port=80,
            default_action=elbv2.ListenerAction.fixed_response(
                status_code=404,
                content_type="text/plain",
                message_body="Not found"
            )
        )

        api_service = ecs.FargateService(
            self,
            "ApiService",
            cluster=self.cluster,
            task_definition=api_task,
            desired_count=1,
            service_name="scorestream-api",
            assign_public_ip=False,
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS),
            security_groups=[network.sg_api],
            enable_execute_command=True
        )

        api_target_group = http_listener.add_targets(
            "ApiTargetGroup",
            port=8000,
            protocol=elbv2.ApplicationProtocol.HTTP,
            targets=[api_service],
            health_check=elbv2.HealthCheck(
                path="/health",
                interval=Duration.seconds(30),
                timeout=Duration.seconds(10),
                healthy_http_codes="200",
                healthy_threshold_count=2,
                unhealthy_threshold_count=3
            ),
            deregistration_delay=Duration.seconds(30)
        )

        api_execution_role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "secretsmanager:GetSecretValue",
                    "secretsmanager:DescribeSecret",
                ],
                resources=[
                    data.secret_rds.secret_arn,
                    network.secret_anthropic.secret_arn,
                    network.secret_football_data.secret_arn,
                ],
            )
        )

        api_execution_role.add_to_policy(
            iam.PolicyStatement(
                actions=["kms:Decrypt"],
                resources=["*"],
            )
        )

        scheduler_task_role = iam.Role(
            self,
            "SchedulerTaskRole",
            assumed_by=iam.ServicePrincipal("ecs-tasks.amazonaws.com"),
            description="IAM role for ScoreStream scheduler ECS task",
        )

        data.grant_secrets_read(scheduler_task_role)

        scheduler_task_role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "ssmmessages:CreateControlChannel",
                    "ssmmessages:CreateDataChannel",
                    "ssmmessages:OpenControlChannel",
                    "ssmmessages:OpenDataChannel"
                ],
                resources=["*"],
            )
        )

        scheduler_execution_role = iam.Role(
            self,
            "SchedulerExecutionRole",
            assumed_by=iam.ServicePrincipal("ecs-tasks.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name("service-role/AmazonECSTaskExecutionRolePolicy")
            ] 
        )

        data.grant_secrets_read(scheduler_execution_role)

        scheduler_repo = ecr.Repository.from_repository_name(
            self,
            "SchedulerRepo",
            repository_name="scorestream/scheduler"
        )

        scheduler_log_group = logs.LogGroup(
            self,
            "SchedulerLogs",
            log_group_name="/scorestream/scheduler",
            retention=logs.RetentionDays.ONE_WEEK,
            removal_policy=RemovalPolicy.DESTROY
        )

        scheduler_task = ecs.FargateTaskDefinition(
            self,
            "SchedulerTask",
            task_role=scheduler_task_role,
            execution_role=scheduler_execution_role,
            cpu=256,
            memory_limit_mib=512
        )

        scheduler_task.add_container(
            "SchedulerContainer",
            image=ecs.ContainerImage.from_ecr_repository(scheduler_repo, tag="latest"),
            environment={
                "AWS_DEFAULT_REGION": "us-east-1",
                "ARCHIVE BUCKET": f"scorestream-glue-{self.account}",
            },
            secrets={
                "DB_HOST": ecs.Secret.from_secrets_manager(data.secret_rds, field="host"),
                "DB_PORT": ecs.Secret.from_secrets_manager(data.secret_rds, field="port"),
                "DB_USER": ecs.Secret.from_secrets_manager(data.secret_rds, field="username"),
                "DB_PASSWORD": ecs.Secret.from_secrets_manager(data.secret_rds, field="password"),
                "DB_NAME": ecs.Secret.from_secrets_manager(data.secret_rds, field="dbname"),
            },
            logging=ecs.LogDrivers.aws_logs(
                stream_prefix="scheduler",
                log_group=scheduler_log_group
            )
        )

        eventbridge_role = iam.Role(
            self,
            "EventBridgeSchedulerRole",
            assumed_by=iam.ServicePrincipal("scheduler.amazonaws.com"),
            description="IAM role for ScoreStream EventBridge Scheduler",
        )

        eventbridge_role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "ecs:RunTask",
                ],
                resources=[scheduler_task.task_definition_arn],
            )
        )

        eventbridge_role.add_to_policy(
            iam.PolicyStatement(
                actions=["iam:PassRole"],
                resources=[scheduler_task_role.role_arn, scheduler_execution_role.role_arn],
            )
        )

        # Helper to build the ECS target input
        def ecs_target(job_name: str) -> dict:
            return {
                "arn": f"arn:aws:ecs:{self.region}:{self.account}:cluster/scorestream",
                "roleArn": eventbridge_role.role_arn,
                "ecsParameters": {
                    "taskDefinitionArn": scheduler_task.task_definition_arn,
                    "taskCount": 1,
                    "launchType": "FARGATE",
                    "networkConfiguration": {
                        "awsvpcConfiguration": {
                            "subnets": [
                                subnet.subnet_id
                                for subnet in network.vpc.private_subnets
                            ],
                            "securityGroups": [
                                network.sg_producer.security_group_id
                            ],
                            "assignPublicIp": "DISABLED",
                        }
                    },
                    "overrides": {
                        "containerOverrides": [
                            {
                                "name": "SchedulerContainer",
                                "environment": [
                                    {
                                        "name": "SCHEDULER_JOB",
                                        "value": job_name,
                                    }
                                ],
                            }
                        ]
                    },
                },
            }

        # Standings refresh — every 30 minutes
        scheduler.CfnSchedule(
            self, "StandingsSchedule",
            schedule_expression="rate(30 minutes)",
            flexible_time_window=scheduler.CfnSchedule.FlexibleTimeWindowProperty(
                mode="OFF",
            ),
            target=scheduler.CfnSchedule.TargetProperty(
                arn=f"arn:aws:ecs:{self.region}:{self.account}:cluster/scorestream",
                role_arn=eventbridge_role.role_arn,
                ecs_parameters=scheduler.CfnSchedule.EcsParametersProperty(
                    task_definition_arn=scheduler_task.task_definition_arn,
                    task_count=1,
                    launch_type="FARGATE",
                    network_configuration=scheduler.CfnSchedule.NetworkConfigurationProperty(
                        awsvpc_configuration=scheduler.CfnSchedule.AwsVpcConfigurationProperty(
                            subnets=[
                                subnet.subnet_id
                                for subnet in network.vpc.private_subnets
                            ],
                            security_groups=[network.sg_producer.security_group_id],
                            assign_public_ip="DISABLED",
                        )
                    ),
                ),
                input=json.dumps({
                    "containerOverrides": [
                        {
                            "name": "SchedulerContainer",
                            "environment": [
                                {"name": "SCHEDULER_JOB", "value": "standings"}
                            ],
                        }
                    ]
                }),
            ),
            name="scorestream-standings-refresh",
        )

        # Daily archive — midnight UTC
        scheduler.CfnSchedule(
            self, "ArchiveSchedule",
            schedule_expression="cron(0 0 * * ? *)",
            flexible_time_window=scheduler.CfnSchedule.FlexibleTimeWindowProperty(
                mode="OFF",
            ),
            target=scheduler.CfnSchedule.TargetProperty(
                arn=f"arn:aws:ecs:{self.region}:{self.account}:cluster/scorestream",
                role_arn=eventbridge_role.role_arn,
                ecs_parameters=scheduler.CfnSchedule.EcsParametersProperty(
                    task_definition_arn=scheduler_task.task_definition_arn,
                    task_count=1,
                    launch_type="FARGATE",
                    network_configuration=scheduler.CfnSchedule.NetworkConfigurationProperty(
                        awsvpc_configuration=scheduler.CfnSchedule.AwsVpcConfigurationProperty(
                            subnets=[
                                subnet.subnet_id
                                for subnet in network.vpc.private_subnets
                            ],
                            security_groups=[network.sg_producer.security_group_id],
                            assign_public_ip="DISABLED",
                        )
                    ),
                ),
                input=json.dumps({
                    "containerOverrides": [
                        {
                            "name": "SchedulerContainer",
                            "environment": [
                                {"name": "SCHEDULER_JOB", "value": "archive"}
                            ],
                        }
                    ]
                }),
            ),
            name="scorestream-daily-archive",
        )