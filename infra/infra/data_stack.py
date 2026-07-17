from aws_cdk import (
    Stack,
    aws_ec2 as ec2,
    aws_rds as rds,
    aws_s3 as s3,
    aws_iam as iam,
    aws_elasticache as elasticache,
    RemovalPolicy,
    Duration,
)
from constructs import Construct
from infra.network_stack import NetworkStack

class DataStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, network: NetworkStack, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.network = network

        rds_subnet_group = rds.SubnetGroup(
            self,
            "RDSSubnetGroup",
            description="ScoreStream RDS Subnet group",
            vpc=network.vpc,
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS),
            removal_policy=RemovalPolicy.DESTROY
        )

        self.rds_instance = rds.DatabaseInstance(
            self,
            "ScoreStreamRDS",
            engine=rds.DatabaseInstanceEngine.postgres(
                version=rds.PostgresEngineVersion.VER_15
            ),
            instance_type=ec2.InstanceType.of(
                ec2.InstanceClass.BURSTABLE3,
                ec2.InstanceSize.MICRO
            ),
            vpc=network.vpc,
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS),
            subnet_group=rds_subnet_group,
            security_groups=[network.sg_rds],
            database_name="scorestream",
            credentials=rds.Credentials.from_generated_secret(username="scorestream", secret_name="scorestream/rds-credentials"),
            multi_az=False,
            allocated_storage=20,
            max_allocated_storage=100,
            removal_policy=RemovalPolicy.DESTROY,
            storage_encrypted=True,
            backup_retention=Duration.days(0),
            deletion_protection=False,
            publicly_accessible=False
        )

        self.secret_rds = self.rds_instance.secret

        redis_subnet_group = elasticache.CfnSubnetGroup(
            self,
            "RedisSubnetGroup",
            description="ScoreStream Redis Subnet group",
            subnet_ids=[subnet.subnet_id for subnet in network.vpc.private_subnets],
            cache_subnet_group_name="scorestream-redis"
        )

        self.redis_cluster = elasticache.CfnCacheCluster(
            self,
            "ScoreStreamRedis",
            engine="redis",
            cache_node_type="cache.t3.micro",
            num_cache_nodes=1,
            cluster_name="scorestream-redis",
            vpc_security_group_ids=[network.sg_redis.security_group_id],
            cache_subnet_group_name=redis_subnet_group.cache_subnet_group_name,
            engine_version="7.0",
        )

        self.redis_cluster.add_dependency(redis_subnet_group)

        self.redis_endpoint = self.redis_cluster.attr_redis_endpoint_address
        self.redis_port = self.redis_cluster.attr_redis_endpoint_port

        self.rds_endpoint = self.rds_instance.db_instance_endpoint_address
        self.rds_port = self.rds_instance.db_instance_endpoint_port

        ## BASTION GROUP - TEMPORARY, REMOVE WHEN NOT NEEDED

        # self.bastion = ec2.BastionHostLinux(
        #     self, "Bastion",
        #     vpc=network.vpc,
        #     subnet_selection=ec2.SubnetSelection(
        #         subnet_type=ec2.SubnetType.PUBLIC
        #     ),
        #     instance_name="scorestream-bastion",
        #     security_group=network.sg_bastion,
        # )

        # self.bastion.instance.role.add_managed_policy(
        #     iam.ManagedPolicy.from_aws_managed_policy_name(
        #         "SecretsManagerReadWrite"
        #     )
        # )

        # ec2.CfnSecurityGroupIngress(
        #     self, "BastionToRds",
        #     group_id=network.sg_rds.security_group_id,
        #     ip_protocol="tcp",
        #     from_port=5432,
        #     to_port=5432,
        #     source_security_group_id=network.sg_bastion.security_group_id,
        #     description="PostgreSQL from bastion - temporary",
        # )

        self.glue_bucket = s3.Bucket(
            self,
            "GlueBucket",
            bucket_name=f"scorestream-glue-{self.account}",
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
            versioned=False,
            encryption=s3.BucketEncryption.S3_MANAGED
        )

    def grant_secrets_read(self, role):
        self.network.secret_anthropic.grant_read(role)
        self.network.secret_football_data.grant_read(role)
        self.secret_rds.grant_read(role)

    def grant_glue_bucket_access(self, role):
        self.glue_bucket.grant_read_write(role)