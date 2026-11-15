# Amazon CloudWatch — Logs, Metrics, and Alarms

**Status: partially implemented in Terraform; AWS resources are not verified.**
Terraform defines ECS log groups with configurable retention, Container
Insights, and ALB/RDS metric alarms. Optional email notification uses SNS and
requires confirming the subscription. The module does not yet alarm on
application-level errors, queue depth, budget spend, or browser-worker task
health.

## Architecture and permissions

ECS sends container stdout/stderr through the task execution role to log groups
named `/ecs/<project>/<service>`. The execution role needs the standard ECS
CloudWatch Logs actions. Operators need read-only log/metric/alarm access;
creating or changing alarms needs CloudWatch and SNS permissions.

## Inspect and deploy

In AWS Console, open CloudWatch → Log groups, Metrics, and Alarms in the
selected region. CLI examples:

```sh
aws logs describe-log-groups --log-group-name-prefix /ecs/jobpilot
aws cloudwatch describe-alarms --alarm-name-prefix jobpilot
```

Terraform configuration is in `infra/terraform/ecs.tf` and `monitoring.tf`.
Run `terraform plan` and inspect changes before an approved apply. Log storage,
ingestion, custom metrics, dashboards, and alarms can incur charges; set
retention deliberately and review current regional pricing.

## Troubleshooting and cleanup

For missing logs, check task execution-role permissions, region, log group,
container stdout/stderr, and ECS events. For alarms stuck in insufficient data,
check metric dimensions and whether tasks have emitted data. Deleting a log
group removes retained logs; export anything required before changing
retention or deleting resources.
