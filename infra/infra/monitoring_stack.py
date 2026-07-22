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

        