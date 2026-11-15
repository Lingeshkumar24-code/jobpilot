# AWS IAM — Identity and Access Management

**Status: Terraform roles implemented; account-side deployment remains pending.** IAM defines identities, roles, and policies. JobPilot uses ECS task execution permissions for ECR pulls/logs/secrets, a backend task role for private resume S3 access, and a browser worker role with no AWS permissions.

## Safe operating model

Use a personal IAM Identity Center/assumed role with MFA for humans. Never create root access keys. GitHub Actions should assume a short-lived role through OIDC, restricted to this repository and production environment; that OIDC role is not yet provisioned by this Terraform root. ECS tasks should use task roles instead of static access keys.

Inspect roles in IAM Console → Roles. CLI read-only inspection: `aws iam get-role --role-name <role>` and `aws iam list-attached-role-policies --role-name <role>`. Terraform policy definitions are in `infra/terraform/iam.tf`. Limit changes to named resources and review `terraform plan`; broad IAM permissions are a security risk. IAM itself has no direct charge, but services it enables may.

Troubleshoot `AccessDenied` by checking the caller identity, task role versus execution role, resource ARN, region, and explicit denies. Removing a role can stop deployments or break S3/log access; inspect dependencies before deletion. Never run destructive IAM or Terraform changes without a reviewed plan.
