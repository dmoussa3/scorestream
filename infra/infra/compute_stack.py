from aws_cdk import (
    Stack,
    aws_ecs as ecs,
    aws_iam as iam,
    aws_ecr as ecr,
    aws_logs as logs,
    aws_ec2 as ec2,
    aws_glue as glue,
    Duration,
    RemovalPolicy,
    Fn
)

from constructs import Construct
from infra.network_stack import NetworkStack
from infra.data_stack import DataStack
from infra.msk_stack import MskStack

class ComputeStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, network: NetworkStack, data: DataStack, msk: MskStack, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.cluster = ecs.Cluster(
            self,
            "ScoreStreamCluster",
            cluster_name="scorestream",
            vpc=network.vpc,
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
                "DB_PASS": ecs.Secret.from_secrets_manager(data.secret_rds, field="password"),
                "DB_NAME": ecs.Secret.from_secrets_manager(data.secret_rds, field="dbname"),
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