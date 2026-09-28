#!/bin/bash
set -e

echo "=== ScoreStream AWS Restart ==="

# 1 — Network (NAT gateway back to 1 must be done in CDK before running this)
echo "Deploying NetworkStack..."
cd infra && cdk deploy NetworkStack --require-approval never

# 2 — Data layer
echo "Deploying DataStack..."
cdk deploy DataStack --require-approval never

# 3 — MSK
echo "Deploying MskStack..."
cdk deploy MskStack --require-approval never

# 4 — Upload Glue script
echo "Uploading Glue script..."
cd ..
aws s3 cp spark/streaming_aws.py \
    s3://scorestream-glue-299763762000/scripts/streaming_job.py

# 5 — Compute
echo "Deploying ComputeStack..."
cd infra && cdk deploy ComputeStack --require-approval never

# 6 — Frontend, Edge and Monitoring
cdk deploy EdgeStack --require-approval never

CLOUDFRONT_DOMAIN=$(aws cloudformation describe-stacks \
    --stack-name EdgeStack \
    --query 'Stacks[0].Outputs[?OutputKey==`CloudFrontDomainName`].OutputValue' \
    --output text 2>/dev/null || echo "")

cd ../frontend
REACT_APP_API_URL=https://$CLOUDFRONT_DOMAIN \
REACT_APP_WS_URL=wss://$CLOUDFRONT_DOMAIN/ws \
REACT_APP_CHAT_WS_URL=wss://$CLOUDFRONT_DOMAIN/ws/chat \
npm run build

cd ../infra
cdk deploy EdgeStack --require-approval never
cdk deploy MonitoringStack --require-approval never

# 7 — Start Glue
echo "Starting Glue streaming job..."
aws glue start-job-run --job-name scorestream-streaming

echo "=== Restart complete ==="
echo "CloudFront URL: https://$CLOUDFRONT_DOMAIN"