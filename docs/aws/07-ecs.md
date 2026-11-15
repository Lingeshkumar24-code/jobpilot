# Amazon ECS Fargate — Service Deployment

**Status: task definitions and services exist in Terraform; no deployment verified.** ECS definitions cover the FastAPI backend, Next.js frontend, and isolated Playwright browser worker. Private tasks route through the ALB and use CloudWatch logs. The worker task count defaults to zero; scale it only while browser work is requested. n8n and a durable background worker are not ECS services yet.

Inspect ECS → Clusters → Services → Tasks and Events. CLI: `aws ecs describe-services --cluster <cluster> --services backend frontend browser-worker`. Deployment workflow builds/pushes ECR images and forces service redeployment after the production approval gate. Check stopped-task reasons, target health, task/execution roles, and logs when tasks fail.

Fargate charges for requested vCPU/memory and runtime, plus networking and logs. Keep desired counts low for development and review the cost of always-on frontend/API. Deployment circuit breakers request rollback on failures; verify the prior task definition and image are retained. Scaling to zero makes a service unavailable. Do not delete a cluster until data services and dependencies are handled.
