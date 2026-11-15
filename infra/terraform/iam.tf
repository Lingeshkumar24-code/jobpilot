locals {
  database_url = "postgresql+asyncpg://${urlencode(var.db_username)}:${urlencode(var.db_password)}@${aws_db_instance.main.address}:${aws_db_instance.main.port}/${var.db_name}"

  secret_parameters = {
    DATABASE_URL            = local.database_url
    JWT_SECRET              = var.jwt_secret
    APPROVAL_SIGNING_SECRET = var.approval_signing_secret
    BROWSER_WORKER_SECRET   = var.browser_worker_secret
    N8N_WEBHOOK_SECRET      = var.n8n_webhook_secret
  }
}

resource "aws_ssm_parameter" "secrets" {
  for_each = local.secret_parameters

  name  = "/${local.name}/${each.key}"
  type  = "SecureString"
  value = each.value

  tags = { Name = "${local.name}-${each.key}" }
}

data "aws_kms_alias" "ssm" {
  name = "alias/aws/ssm"
}

data "aws_iam_policy_document" "ecs_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "execution" {
  name               = "${local.name}-ecs-execution"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json
}

resource "aws_iam_role_policy_attachment" "execution_managed" {
  role       = aws_iam_role.execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

data "aws_iam_policy_document" "execution_secrets" {
  statement {
    actions   = ["ssm:GetParameters", "ssm:GetParameter"]
    resources = [for parameter in aws_ssm_parameter.secrets : parameter.arn]
  }

  statement {
    actions   = ["kms:Decrypt"]
    resources = [data.aws_kms_alias.ssm.target_key_arn]
  }
}

resource "aws_iam_role_policy" "execution_secrets" {
  name   = "read-ssm-secrets"
  role   = aws_iam_role.execution.id
  policy = data.aws_iam_policy_document.execution_secrets.json
}

resource "aws_iam_role" "backend_task" {
  name               = "${local.name}-backend-task"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json
}

data "aws_iam_policy_document" "backend_s3" {
  statement {
    actions = [
      "s3:PutObject",
      "s3:GetObject",
      "s3:DeleteObject",
      "s3:ListBucket",
    ]
    resources = [
      aws_s3_bucket.resumes.arn,
      "${aws_s3_bucket.resumes.arn}/*",
    ]
  }
}

resource "aws_iam_role_policy" "backend_s3" {
  name   = "resume-storage"
  role   = aws_iam_role.backend_task.id
  policy = data.aws_iam_policy_document.backend_s3.json
}

# The worker receives no AWS permissions. It reaches the internet through the
# NAT gateway and is otherwise isolated.
resource "aws_iam_role" "worker_task" {
  name               = "${local.name}-worker-task"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json
}
