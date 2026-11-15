# Terraform — Infrastructure as Code

**Status: Terraform root implemented, not applied or validated against an AWS account.**
The current module describes VPC networking, NAT, ALB, ECS/Fargate, RDS,
private S3, ECR, IAM/SSM secrets, CloudWatch, and SNS. It does not yet create
the GitHub OIDC role, EC2 learning environment, SQS, Lambda, API Gateway, or
n8n service. See `infra/terraform/README.md` for the resource inventory and
manual prerequisites.

## Workflow

Terraform records desired infrastructure as code. Use a separate state file
and secret set per environment; remote state with encryption, locking, and
restricted access is recommended before team use. Never commit `.tfstate`,
`.tfvars`, or secrets. Keep a reviewed plan artifact for every deployment.

```sh
cd infra/terraform
terraform init
terraform fmt -check -recursive
terraform validate
terraform plan -out=tfplan
terraform show tfplan
```

Only apply a reviewed plan when explicitly authorized. `terraform destroy` is
destructive and can delete resume files and databases; back up data and review
the destroy plan first. IAM should be limited to the resources managed by this
root. To inspect state, use `terraform state list` and `terraform output` only
in a trusted terminal; outputs may contain sensitive infrastructure details.

NAT gateways, load balancers, RDS, and running Fargate tasks have ongoing
regional costs. Use current AWS pricing and the Cost Explorer before applying;
this repository does not provide a reliable fixed cost estimate.
