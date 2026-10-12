from aws_cdk import (
    Stack,
    aws_rds as rds,
    aws_ec2 as ec2,
    aws_secretsmanager as secretsmanager,
)
from constructs import Construct


class RdsStack(Stack):
    def __init__(self, scope, construct_id: str, network, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.rds_instance = rds.DatabaseInstance.from_database_instance_attributes(
            self, "ScoreStreamRDS",
            instance_identifier="scorestream-rds",
            instance_endpoint_address="scorestream-rds.csx0y2syktme.us-east-1.rds.amazonaws.com",
            port=5432,
            security_groups=[network.sg_rds],
            instance_resource_id="db-5YZOFKECBT7MXJGVQWKMKUBPAQ",
            engine=rds.DatabaseInstanceEngine.postgres(
                version=rds.PostgresEngineVersion.VER_15
            ),
        )

        self.secret_rds = secretsmanager.Secret.from_secret_name_v2(
            self, "RdsSecret",
            secret_name="scorestream/rds-credentials",
        )

        self.rds_endpoint = self.rds_instance.db_instance_endpoint_address
        self.rds_port = self.rds_instance.db_instance_endpoint_port