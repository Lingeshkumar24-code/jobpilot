# Amazon ECR — Container Registry

**Status: repositories and lifecycle policies exist in Terraform; no images have been pushed from this review.** ECR stores backend, frontend, and browser-worker images. GitHub Actions logs in using the AWS role assumed via OIDC, builds images, and pushes a commit SHA plus `latest` tag.

Inspect ECR → Repositories in the Console. CLI: `aws ecr describe-repositories --repository-names jobpilot-backend jobpilot-frontend jobpilot-browser-worker`. Terraform is in `infra/terraform/storage.tf`; deployment steps are in `.github/workflows/deploy.yml`. Restrict push/pull to the deploy role and ECS execution role. ECR storage and data transfer may incur charges; lifecycle policy limits old images, so confirm rollback images are retained.

For pull failures, check repository URI, region, image tag, task execution role, and ECS events. Do not delete a repository used by a task definition. Before deleting images, verify the rollback and current deployment tags remain available.
