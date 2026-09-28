#!/bin/bash
set -e

echo "=== ScoreStream AWS Teardown ==="

# Stop Glue first
RUN_ID=$(aws glue get-job-runs \
    --job-name scorestream-streaming \
    --query 'JobRuns[0].Id' \
    --output text 2>/dev/null || echo "")

if [ ! -z "$RUN_ID" ] && [ "$RUN_ID" != "None" ]; then
    echo "Stopping Glue job..."
    aws glue batch-stop-job-run \
        --job-name scorestream-streaming \
        --job-run-ids $RUN_ID
fi

# Destroy stacks
cd infra
cdk destroy MonitoringStack --force
cdk destroy EdgeStack --force
cdk destroy ComputeStack --force
cdk destroy MskStack --force

# Set NAT to 0 — edit network_stack.py nat_gateways=0 then:
echo "Remember to set nat_gateways=0 in network_stack.py before running:"
echo "  cdk deploy NetworkStack"
echo ""
echo "=== Teardown complete ==="
echo "DataStack and NetworkStack left standing (RDS protected)"