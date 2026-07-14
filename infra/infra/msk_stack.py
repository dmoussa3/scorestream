from aws_cdk import (
    Stack,
    aws_msk_alpha as msk,
    aws_ec2 as ec2,
    RemovalPolicy,
)
from aws_cdk import aws_msk as msk_cfn
from constructs import Construct
from infra.network_stack import NetworkStack

class MskStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, network: NetworkStack, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.network = network

        private_subnets = network.vpc.select_subnets(subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS)

        msk_config = msk_cfn.CfnConfiguration(
            self,
            "MskConfig",
            name="scorestream-msk-config",
            kafka_versions_list=["3.6.0"],
            server_properties=(
                "auto.create.topics.enable=true\n"
                "default.replication.factor=2\n"
                "min.insync.replicas=1\n"
                "num.partitions=3\n"
            )
        )

        self.cluster = msk.Cluster(
            self,
            "ScoreStreamMsk",
            cluster_name="scorestream-kafka",
            kafka_version=msk.KafkaVersion.V3_6_0,
            number_of_broker_nodes=2,
            vpc=network.vpc,
            instance_type=ec2.InstanceType.of(ec2.InstanceClass.M5, ec2.InstanceSize.LARGE),
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS),
            security_groups=[network.sg_msk],
            encryption_in_transit=msk.EncryptionInTransitConfig(    
                client_broker=msk.ClientBrokerEncryption.TLS  
            ),
            client_authentication=msk.ClientAuthentication.sasl(   
                iam=True
            ),
            ebs_storage_info=msk.EbsStorageInfo(   
                volume_size=20
            ),
            removal_policy=RemovalPolicy.DESTROY,
            configuration_info=msk.ClusterConfigurationInfo(
                arn=msk_config.attr_arn,
                revision=msk_config.attr_latest_revision_revision
            )
        )

        self.bootstrap_brokers_iam = self.cluster.bootstrap_brokers_sasl_iam