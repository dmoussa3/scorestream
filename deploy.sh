#!/bin/bash
set -e

echo "=== ScoreStream AWS Deployment ==="

# 1 — Deploy network and data layer
# Remember to set nat_gateways=1 in network_stack.py before running
cd infra
cdk deploy NetworkStack --require-approval never
cdk deploy DataStack --require-approval never
cdk deploy MskStack --require-approval never   # 15-25 min

# 2 — Upload Glue script
cd ..
aws s3 cp spark/streaming_job_aws.py \
    s3://scorestream-glue-299763762000/scripts/streaming_job.py

# 3 — Deploy compute
cd infra
cdk deploy ComputeStack --require-approval never

# 4 — Deploy EdgeStack first to get CloudFront domain
cdk deploy EdgeStack --require-approval never

CLOUDFRONT_DOMAIN=$(aws cloudformation describe-stacks \
    --stack-name EdgeStack \
    --query 'Stacks[0].Outputs[?OutputKey==`CloudFrontDomainName`].OutputValue' \
    --output text)

echo "CloudFront domain: $CLOUDFRONT_DOMAIN"

# 5 — Rebuild frontend with correct domain
cd ../frontend
REACT_APP_API_URL=https://$CLOUDFRONT_DOMAIN \
REACT_APP_WS_URL=wss://$CLOUDFRONT_DOMAIN/ws \
REACT_APP_CHAT_WS_URL=wss://$CLOUDFRONT_DOMAIN/ws/chat \
npm run build

# 6 — Redeploy EdgeStack with correct build
cd ../infra
cdk deploy EdgeStack --require-approval never
cdk deploy MonitoringStack --require-approval never

# 7 — Start Glue
aws glue start-job-run --job-name scorestream-streaming

echo ""
echo "=== Deployment complete ==="
echo "CloudFront URL: https://$CLOUDFRONT_DOMAIN"
echo "Remember to confirm SNS email subscription"