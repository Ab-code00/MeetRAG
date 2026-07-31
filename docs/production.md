# Production deployment baseline

## AWS topology

- Run the API and Celery workers as separate ECS services with independent autoscaling.
- Place ECS tasks, RDS MySQL, ElastiCache Redis, and Qdrant in private subnets. Only the load balancer is public.
- Use S3 gateway endpoints and task roles instead of static AWS credentials.
- Store Groq, OpenRouter, JWT, database, and Qdrant secrets in AWS Secrets Manager.
- Enable RDS encryption, automated backups, point-in-time recovery, Multi-AZ, and deletion protection.
- Use a managed Qdrant cluster or persistent encrypted EBS with snapshots and tested restore procedures.
- Terminate TLS at an ALB or CloudFront and restrict API CORS to the deployed frontend origin.

## Release process

1. Run unit, integration, tenant-isolation, migration, and frontend build checks.
2. Build immutable API, worker, and frontend images and scan them for vulnerabilities.
3. Apply Alembic migrations from a one-off deployment task before shifting traffic.
4. Deploy workers and API with rolling health checks.
5. Verify upload, a synthetic pipeline run, tenant-filtered retrieval, and cited answering.
6. Monitor error rate, stage latency, queue depth, token usage, and provider limits.

## Required alerts

- API error rate and p95 latency
- Celery queue age and dead-lettered jobs
- Stage failure rate and processing latency
- RDS connections, storage, replica lag, and backup failures
- Qdrant availability, disk usage, and indexing failures
- S3 upload failures
- Groq and OpenRouter rate limiting
- Retrievals with no evidence and generated answers rejected for missing citations

## Data lifecycle

Recordings are soft-deleted from the application first, removed from S3 by a retention policy, and recorded in the audit trail. Raw transcript immutability is an audit invariant; legal deletion requires a separately approved tenant-erasure workflow that removes the complete tenant dataset rather than mutating individual raw transcript rows.

