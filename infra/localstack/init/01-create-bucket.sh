#!/bin/sh
set -eu
awslocal s3api head-bucket --bucket "${AWS_S3_BUCKET:-meetai-recordings}" 2>/dev/null || \
  awslocal s3api create-bucket --bucket "${AWS_S3_BUCKET:-meetai-recordings}"
awslocal s3api put-bucket-cors --bucket "${AWS_S3_BUCKET:-meetai-recordings}" --cors-configuration '{"CORSRules":[{"AllowedHeaders":["*"],"AllowedMethods":["GET","PUT","HEAD"],"AllowedOrigins":["http://localhost:3000"],"ExposeHeaders":["ETag"],"MaxAgeSeconds":3600}]}'

