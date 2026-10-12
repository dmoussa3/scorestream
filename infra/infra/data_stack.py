from aws_cdk import (
    Stack,
    aws_ec2 as ec2,
    aws_s3 as s3,
    aws_elasticache as elasticache,
    RemovalPolicy,
    aws_secretsmanager as secretsmanager,
)
from constructs import Construct
from infra.network_stack import NetworkStack
from infra.rds_stack import RdsStack

class DataStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, network: NetworkStack, rds: RdsStack, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.network = network
        self.rds_instance = rds.rds_instance
        self.secret_rds = rds.secret_rds
        self.rds_endpoint = rds.rds_endpoint
        self.rds_port = rds.rds_port

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