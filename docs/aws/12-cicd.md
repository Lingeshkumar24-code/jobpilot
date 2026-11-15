# GitHub Actions — CI/CD to AWS

**Status: workflows exist; AWS deployment is not configured or verified.**
`.github/workflows/ci.yml` runs backend checks, worker tests, frontend checks,
and Terraform validation. `deploy.yml` uses GitHub OIDC, pushes images to ECR,
forces ECS service deployments, waits for stability, and probes the health URL.
The deploy job requires a GitHub `production` environment approval.

## Required setup and permissions

Create an AWS IAM OIDC provider for `token.actions.githubusercontent.com` and a
role restricted to this repository and deployment environment. Grant only
ECR push, ECS update/describe, and `iam:PassRole` for the exact ECS roles used.
Configure GitHub variables `AWS_REGION`, `PUBLIC_API_BASE`, `ECS_CLUSTER`, and
`HEALTH_URL`; configure secrets `AWS_DEPLOY_ROLE_ARN` and `ECR_REGISTRY`.
Never add long-lived AWS access keys. Verify the production environment has
reviewers enabled.

## Run and troubleshoot

Pull requests run CI. Production deploys are manually triggered or tag-triggered
and wait at the environment approval gate. Inspect Actions logs, then ECS
service events, task stopped reasons, CloudWatch logs, and ALB target health.
The ECS deployment circuit breaker is configured to roll back failed service
deployments; verify the previous task definition and image remain available.

ECR image storage and build/deploy infrastructure incur costs. Check AWS
Budgets and ECR lifecycle rules. No deploy has been confirmed until the
workflow completes and `/health/ready` reports a healthy database.
