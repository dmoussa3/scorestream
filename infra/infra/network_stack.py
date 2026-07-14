from aws_cdk import (
    # Duration,
    Stack,
    # aws_sqs as sqs,
    aws_ec2 as ec2,
    aws_secretsmanager as secretsmanager,
)
from constructs import Construct

class NetworkStack(Stack):

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.vpc = ec2.Vpc(
            self,
            "ScoreStreamVPC",
            max_azs=2,
            nat_gateways=1,
            subnet_configuration=[
                ec2.SubnetConfiguration(
                    name="public",
                    subnet_type=ec2.SubnetType.PUBLIC,
                    cidr_mask=24,
                ),
                ec2.SubnetConfiguration(
                    name="private",
                    subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS,
                    cidr_mask=24,
                ),
            ],
        )

        self.sg_alb = ec2.SecurityGroup(
            self,
            "SgAlb",
            vpc=self.vpc,
            description="ALB security group",
            allow_all_outbound=True,
        )

        self.sg_api = ec2.SecurityGroup(
            self,
            "SgApi",
            vpc=self.vpc,
            description="API ECS task security group",
            allow_all_outbound=True,
        )

        self.sg_producer = ec2.SecurityGroup(
            self,
            "SgProducer",
            vpc=self.vpc,
            description="Producer ECS task security group",
            allow_all_outbound=True,
        )

        self.sg_rds = ec2.SecurityGroup(
            self, 
            "SgRds",
            vpc=self.vpc,
            description="RDS PostgreSQL security group",
            allow_all_outbound=False,
        )

        self.sg_redis = ec2.SecurityGroup(
            self, 
            "SgRedis",
            vpc=self.vpc,
            description="Elasticache Redis security group",
            allow_all_outbound=False,
        )

        self.sg_msk = ec2.SecurityGroup(
            self, 
            "SgMsk",
            vpc=self.vpc,
            description="MSK Kafka security group",
            allow_all_outbound=False,
        )

        self.sg_glue = ec2.SecurityGroup(
            self, 
            "SgGlue",
            vpc=self.vpc,
            description="Glue streaming job security group",
            allow_all_outbound=True,
        )

        self.sg_bastion = ec2.SecurityGroup(
            self,
            "SgBastion",
            vpc=self.vpc,
            description="Bastion host security group",
            allow_all_outbound=True,
        )

        self.sg_rds.add_ingress_rule(
            peer=self.sg_bastion,
            connection=ec2.Port.tcp(5432),
            description="PostgreSQL port from Bastion host",
        )

        self.sg_alb.add_ingress_rule(
            peer=ec2.Peer.any_ipv4(),
            connection=ec2.Port.tcp(443),
            description="HTTPS from internet",
        )

        self.sg_alb.add_ingress_rule(
            peer=ec2.Peer.any_ipv4(),
            connection=ec2.Port.tcp(80),
            description="HTTP from internet for redirect",
        )

        self.sg_api.add_ingress_rule(
            peer=self.sg_alb,
            connection=ec2.Port.tcp(8000),
            description="FastAPI port from ALB",
        )

        self.sg_rds.add_ingress_rule(
            peer=self.sg_api,
            connection=ec2.Port.tcp(5432),
            description="PostgreSQL port from API ECS task",
        )

        self.sg_rds.add_ingress_rule(
            peer=self.sg_producer,
            connection=ec2.Port.tcp(5432),
            description="PostgreSQL port from Producer ECS task",
        )

        self.sg_rds.add_ingress_rule(
            peer=self.sg_glue,
            connection=ec2.Port.tcp(5432),
            description="PostgreSQL port from Glue job",
        )

        self.sg_redis.add_ingress_rule(
            peer=self.sg_api,
            connection=ec2.Port.tcp(6379),
            description="Redis port from API ECS task",
        )

        self.sg_msk.add_ingress_rule(
            peer=self.sg_producer,
            connection=ec2.Port.tcp(9098),
            description="MSK IAM auth from Producer ECS task",
        )

        self.sg_msk.add_ingress_rule(
            peer=self.sg_glue,
            connection=ec2.Port.tcp(9098),
            description="MSK IAM auth from Glue job",
        )

        self.sg_msk.add_ingress_rule(
            peer=self.sg_msk,
            connection=ec2.Port.tcp(2181),
            description="ZooKeeper Internal",
        )

        self.sg_glue.add_ingress_rule(
            peer=self.sg_glue,
            connection=ec2.Port.all_traffic(),
            description="Glue self-reference required for VPC job",
        )

        self.secret_anthropic = secretsmanager.Secret(
            self,
            "AnthropicApiKey",
            secret_name="scorestream/anthropic_api_key",
            description="Anthropic API Key for LLM access",
        )

        self.secret_football_data = secretsmanager.Secret(
            self,
            "FootballDataApiKey",
            secret_name="scorestream/football_data_api_key",
            description="football-data.org API Key for historical football data backfill",
        )

        # IAM Roles — defined alongside their services in compute_stack.py

        # producer_task_role
        # - secretsmanager:GetSecretValue on scorestream/anthropic-api-key
        # - secretsmanager:GetSecretValue on scorestream/football-data-api-key
        # - kafka:* on the MSK cluster ARN (scoped to the two topics)

        # api_task_role
        # - secretsmanager:GetSecretValue on scorestream/anthropic-api-key
        # - secretsmanager:GetSecretValue on scorestream/rds-credentials

        # glue_job_role
        # - secretsmanager:GetSecretValue on scorestream/rds-credentials
        # - kafka:* on the MSK cluster ARN (consumer group, read topics)
        # - s3:GetObject, s3:PutObject on the checkpoints and archive buckets
        # - ec2:* subset for Glue VPC connectivity (Glue requires specific EC2 permissions)
        
        def grant_secret_read(self, role):
            self.secret_anthropic.grant_read(role)
            self.secret_football_data.grant_read(role)