# Terraform — JobPilot AI Infrastructure

This root module currently defines the AWS VPC/subnets/NAT, security groups,
Application Load Balancer, ECS Fargate cluster and services for API, frontend,
and browser worker, ECR, private RDS PostgreSQL, private versioned S3, SSM
SecureString parameters, IAM task/execution roles, CloudWatch log groups and
alarms, and optional SNS email alerts. It targets `ap-south-1` by default.

## Before applying

This is a billable architecture. NAT Gateway, ALB, RDS, and running Fargate
services have ongoing charges even at low traffic. Review current AWS pricing
for the selected region and instance sizes, configure a budget in the AWS
Billing console, then run `terraform plan` and inspect every change. No apply
or destroy is performed automatically. Keep `worker_desired_count = 0` while
browser automation is idle.

## Setup

1. Install Terraform and AWS CLI; configure an IAM identity with only the
   permissions required for this environment.
2. Copy `terraform.tfvars.example` to a private `terraform.tfvars` and set
   strong secrets locally. Never commit that file.
3. Set a real ACM certificate ARN for HTTPS before production use. Without
   one, the load balancer uses HTTP and is unsuitable for production.
4. Run `terraform init`, `terraform fmt -check`, `terraform validate`, and
   `terraform plan` from this directory.
5. Review cost and plan output before manually applying. Configure GitHub OIDC
   separately; this Terraform root currently does not provision the GitHub
   OIDC deploy role.

The module does not deploy EC2, SQS, Lambda, API Gateway, n8n, or a
background-worker service. Those remain work items. RDS uses private
PostgreSQL with encryption and backups; validate pgvector extension
installation before enabling embeddings in production.

`terraform destroy` can delete data and incur final charges. Back up data and
explicitly review the plan before running it.
