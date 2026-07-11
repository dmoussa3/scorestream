#!/usr/bin/env python3
import os

import aws_cdk as cdk

from infra.network_stack import NetworkStack
from infra.data_stack import DataStack

app = cdk.App()
network_stack = NetworkStack(app, "NetworkStack",
    env=cdk.Environment(
        account=os.getenv('CDK_DEFAULT_ACCOUNT'), 
        region=os.getenv('CDK_DEFAULT_REGION')
    ),
)

data_stack = DataStack(app, "DataStack", network=network_stack,
    env=cdk.Environment(
        account=os.getenv('CDK_DEFAULT_ACCOUNT'), 
        region=os.getenv('CDK_DEFAULT_REGION')
    ),
)

app.synth()
