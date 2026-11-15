# Amazon VPC — Networking Foundation

**Status: Terraform implementation exists; not applied.** `network.tf` defines a two-AZ VPC, public and private subnets, internet gateway, NAT gateway, and route tables. `security.tf` restricts ALB, API, worker, frontend, and database paths. The ALB is public; ECS tasks and RDS are private.

Inspect VPC → Your VPCs/Subnets/Route tables/Security groups in the AWS Console. CLI: `aws ec2 describe-vpcs --filters Name=tag:Project,Values=jobpilot` and `aws ec2 describe-subnets --filters Name=vpc-id,Values=<vpc-id>`. Deploy through the Terraform directory after reviewing a plan; no VPC has been provisioned here.

For operator access, prefer Systems Manager Session Manager and least-privilege IAM. No SSH ingress is defined. Check subnet routes, DNS settings, security group references, and NAT/IGW routes when tasks cannot reach required endpoints. A NAT Gateway has an hourly and data-processing charge; it can be a significant baseline cost. Deleting the VPC interrupts every dependent service and may require deleting RDS first; review Terraform dependencies and protect data.
