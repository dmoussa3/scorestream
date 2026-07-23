#!/usr/bin/env python3
import os

import aws_cdk as cdk

from infra.network_stack import NetworkStack
from infra.data_stack import DataStack
from infra.msk_stack import MskStack
from infra.compute_stack import ComputeStack
from infra.edge_stack import EdgeStack
from infra.monitoring_stack import MonitoringStack

env=cdk.Environment(
    account=os.getenv('CDK_DEFAULT_ACCOUNT'), 
    region=os.getenv('CDK_DEFAULT_REGION')
)

app = cdk.App()

network_stack = NetworkStack(app, "NetworkStack", env=env)
data_stack = DataStack(app, "DataStack", network=network_stack, env=env)
msk_stack = MskStack(app, "MskStack", network=network_stack, env=env)
compute_stack = ComputeStack(app, "ComputeStack", network=network_stack, data=data_stack, msk=msk_stack, env=env)
edge_stack = EdgeStack(app, "EdgeStack", compute=compute_stack, env=env)
monitoring_stack = MonitoringStack(app, "MonitoringStack", compute_stack=compute_stack, msk_stack=msk_stack, data_stack=data_stack, alert_email="danielmoussa1203@gmail.com", env=env)

app.synth()
