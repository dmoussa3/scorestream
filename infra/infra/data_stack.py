from aws_cdk import (
    Stack,
    aws_ec2 as ec2,
    aws_rds as rds,
    aws_s3 as s3,
    aws_iam as iam,
    aws_elasticache as elasticache,
    RemovalPolicy,
    aws_secretsmanager as secretsmanager,
    Duration,
    SecretValue
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
            removal_policy=RemovalPolicy.RETAIN
        )

        # On first deploy, use rds.DatabaseInstance(...) to create fresh
        # On subsequent deploys after manual retention, import existing instance:
        # instance_endpoint_address=os.environ.get('RDS_ENDPOINT', ''),
        # instance_resource_id=os.environ.get('RDS_RESOURCE_ID', ''),

        self.rds_instance = rds.DatabaseInstance.from_database_instance_attributes(
            self,
            "ScoreStreamRDS",
            instance_identifier="scorestream-rds",
            instance_endpoint_address="scorestream-rds.csx0y2syktme.us-east-1.rds.amazonaws.com",
            port=5432,
            security_groups=[network.sg_rds],
            instance_resource_id="db-JTPYKPYBA7FTSQYCPTXJTJM4IA",
            engine=rds.DatabaseInstanceEngine.postgres(version=rds.PostgresEngineVersion.VER_15)
        )

        self.secret_rds = secretsmanager.Secret.from_secret_name_v2(
            self,
            "RDSSecret",
            secret_name="scorestream/rds-credentials"
        )

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

        ## BASTION GROUP - TEMPORARY, COMMENT OUT WHEN NOT NEEDED

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
        self.network.secret_proxy.grant_read(role)
        self.secret_rds.grant_read(role)

    def grant_glue_bucket_access(self, role):
        self.glue_bucket.grant_read_write(role)