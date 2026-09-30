#!/bin/bash
set -e

echo "=== ScoreStream AWS Teardown ==="

# 1 — Stop Glue if running
echo "Stopping Glue job..."
RUN_ID=$(aws glue get-job-runs \
    --job-name scorestream-streaming \
    --query 'JobRuns[0].Id' \
    --output text 2>/dev/null || echo "")

if [ ! -z "$RUN_ID" ] && [ "$RUN_ID" != "None" ]; then
    aws glue batch-stop-job-run \
        --job-name scorestream-streaming \
        --job-run-ids $RUN_ID
    echo "Glue job stopped"
else
    echo "No Glue job running — skipping"
fi

# 2 — Destroy stacks in order
echo "Destroying stacks..."
cd infra
cdk destroy MonitoringStack --force
cdk destroy EdgeStack --force
cdk destroy ComputeStack --force
cdk destroy MskStack --force

# 3 — Delete ElastiCache manually (DataStack stays standing for RDS)
echo "Deleting ElastiCache cluster..."
aws elasticache delete-cache-cluster \
    --cache-cluster-id scorestream-redis 2>/dev/null || echo "ElastiCache already deleted"

echo "Waiting for ElastiCache to finish deleting (this can take 10-15 min)..."
while true; do
    STATUS=$(aws elasticache describe-cache-clusters \
        --output text \
        --query "CacheClusters[?CacheClusterId=='scorestream-redis'].CacheClusterStatus" \
        2>/dev/null || echo "")
    if [ -z "$STATUS" ] || [ "$STATUS" = "None" ]; then
        echo "ElastiCache deleted"
        break
    fi
    echo "  Status: $STATUS — waiting 30s..."
    sleep 30
done

# Delete subnet group once cluster is gone
aws elasticache delete-cache-subnet-group \
    --cache-subnet-group-name scorestream-redis 2>/dev/null || true

# 4 — Remove NAT gateway via CDK
# nat_gateways must be set to 0 in network_stack.py before this step
echo ""
echo "Checking nat_gateways setting in network_stack.py..."
if grep -q "nat_gateways=0" ../infra/network_stack.py; then
    echo "nat_gateways=0 confirmed — deploying NetworkStack..."
    cdk deploy NetworkStack --require-approval never
else
    echo "WARNING: nat_gateways is not set to 0 in network_stack.py"
    echo "Please update it and run: cd infra && cdk deploy NetworkStack"
fi

echo ""
echo "=== Teardown complete ==="
echo "DataStack and NetworkStack left standing"
echo "RDS running and protected — data preserved"
echo "Standing cost: ~\$17/month"