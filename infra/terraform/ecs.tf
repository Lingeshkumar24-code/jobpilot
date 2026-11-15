resource "aws_service_discovery_private_dns_namespace" "main" {
  name        = "${var.project}.local"
  description = "Service discovery for ${local.name}"
  vpc         = aws_vpc.main.id
}

resource "aws_service_discovery_service" "worker" {
  name = "worker"

  dns_config {
    namespace_id = aws_service_discovery_private_dns_namespace.main.id

    dns_records {
      ttl  = 10
      type = "A"
    }

    routing_policy = "MULTIVALUE"
  }

  health_check_custom_config {
    failure_threshold = 1
  }
}

resource "aws_ecs_cluster" "main" {
  name = local.name

  setting {
    name  = "containerInsights"
    value = "enabled"
  }
}

resource "aws_cloudwatch_log_group" "backend" {
  name              = "/ecs/${local.name}/backend"
  retention_in_days = var.log_retention_days
}

resource "aws_cloudwatch_log_group" "frontend" {
  name              = "/ecs/${local.name}/frontend"
  retention_in_days = var.log_retention_days
}

resource "aws_cloudwatch_log_group" "worker" {
  name              = "/ecs/${local.name}/worker"
  retention_in_days = var.log_retention_days
}

resource "aws_ecs_task_definition" "backend" {
  family                   = "${local.name}-backend"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = var.backend_cpu
  memory                   = var.backend_memory
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.backend_task.arn

  container_definitions = jsonencode([
    {
      name        = "backend"
      image       = "${aws_ecr_repository.this["backend"].repository_url}:${var.image_tag}"
      essential   = true
      stopTimeout = 30

      portMappings = [{ containerPort = 8000, protocol = "tcp" }]

      environment = [
        { name = "ENVIRONMENT", value = "production" },
        { name = "APP_BASE_URL", value = var.public_origin },
        { name = "FRONTEND_BASE_URL", value = var.public_origin },
        { name = "CORS_ORIGINS", value = var.public_origin },
        { name = "COOKIE_SECURE", value = var.acm_certificate_arn == "" ? "false" : "true" },
        { name = "STORAGE_BACKEND", value = "s3" },
        { name = "S3_BUCKET_RESUMES", value = aws_s3_bucket.resumes.bucket },
        { name = "AWS_REGION", value = var.aws_region },
        { name = "BROWSER_WORKER_URL", value = "http://worker.${aws_service_discovery_private_dns_namespace.main.name}:8100" },
        { name = "RATE_LIMIT_ENABLED", value = "true" },
        { name = "ALLOW_AUTO_SUBMIT", value = "false" },
      ]

      secrets = [
        { name = "DATABASE_URL", valueFrom = aws_ssm_parameter.secrets["DATABASE_URL"].arn },
        { name = "JWT_SECRET", valueFrom = aws_ssm_parameter.secrets["JWT_SECRET"].arn },
        { name = "APPROVAL_SIGNING_SECRET", valueFrom = aws_ssm_parameter.secrets["APPROVAL_SIGNING_SECRET"].arn },
        { name = "BROWSER_WORKER_SECRET", valueFrom = aws_ssm_parameter.secrets["BROWSER_WORKER_SECRET"].arn },
        { name = "N8N_WEBHOOK_SECRET", valueFrom = aws_ssm_parameter.secrets["N8N_WEBHOOK_SECRET"].arn },
      ]

      healthCheck = {
        command     = ["CMD-SHELL", "curl -fsS http://localhost:8000/health || exit 1"]
        interval    = 30
        timeout     = 5
        retries     = 3
        startPeriod = 60
      }

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = aws_cloudwatch_log_group.backend.name
          awslogs-region        = var.aws_region
          awslogs-stream-prefix = "backend"
        }
      }
    }
  ])

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "X86_64"
  }
}

resource "aws_ecs_task_definition" "frontend" {
  family                   = "${local.name}-frontend"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = var.frontend_cpu
  memory                   = var.frontend_memory
  execution_role_arn       = aws_iam_role.execution.arn

  container_definitions = jsonencode([
    {
      name      = "frontend"
      image     = "${aws_ecr_repository.this["frontend"].repository_url}:${var.image_tag}"
      essential = true

      portMappings = [{ containerPort = 3000, protocol = "tcp" }]

      environment = [
        { name = "NODE_ENV", value = "production" },
        { name = "PORT", value = "3000" },
        { name = "HOSTNAME", value = "0.0.0.0" },
      ]

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = aws_cloudwatch_log_group.frontend.name
          awslogs-region        = var.aws_region
          awslogs-stream-prefix = "frontend"
        }
      }
    }
  ])

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "X86_64"
  }
}

resource "aws_ecs_task_definition" "worker" {
  family                   = "${local.name}-worker"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = var.worker_cpu
  memory                   = var.worker_memory
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.worker_task.arn

  container_definitions = jsonencode([
    {
      name        = "browser-worker"
      image       = "${aws_ecr_repository.this["browser-worker"].repository_url}:${var.image_tag}"
      essential   = true
      stopTimeout = 30

      portMappings = [{ containerPort = 8100, protocol = "tcp" }]

      environment = [
        { name = "MAX_SESSIONS", value = "4" },
        { name = "ALLOW_PRIVATE_TARGETS", value = "false" },
      ]

      secrets = [
        { name = "WORKER_SECRET", valueFrom = aws_ssm_parameter.secrets["BROWSER_WORKER_SECRET"].arn },
        { name = "APPROVAL_SIGNING_SECRET", valueFrom = aws_ssm_parameter.secrets["APPROVAL_SIGNING_SECRET"].arn },
      ]

      healthCheck = {
        command     = ["CMD-SHELL", "python -c \"import urllib.request; urllib.request.urlopen('http://localhost:8100/health')\" || exit 1"]
        interval    = 30
        timeout     = 5
        retries     = 3
        startPeriod = 30
      }

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = aws_cloudwatch_log_group.worker.name
          awslogs-region        = var.aws_region
          awslogs-stream-prefix = "worker"
        }
      }
    }
  ])

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "X86_64"
  }
}

resource "aws_ecs_service" "backend" {
  name            = "backend"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.backend.arn
  desired_count   = 1
  launch_type     = "FARGATE"

  health_check_grace_period_seconds = 90

  network_configuration {
    subnets          = aws_subnet.private[*].id
    security_groups  = [aws_security_group.backend.id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.backend.arn
    container_name   = "backend"
    container_port   = 8000
  }

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  deployment_minimum_healthy_percent = 50
  deployment_maximum_percent         = 200

  depends_on = [
    aws_lb_listener.http,
    aws_iam_role_policy.execution_secrets,
    aws_ecs_service.worker,
  ]
}

resource "aws_ecs_service" "frontend" {
  name            = "frontend"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.frontend.arn
  desired_count   = 1
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = aws_subnet.private[*].id
    security_groups  = [aws_security_group.frontend.id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.frontend.arn
    container_name   = "frontend"
    container_port   = 3000
  }

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  deployment_minimum_healthy_percent = 50
  deployment_maximum_percent         = 200

  depends_on = [aws_lb_listener.http]
}

resource "aws_ecs_service" "worker" {
  name             = "browser-worker"
  cluster          = aws_ecs_cluster.main.id
  task_definition  = aws_ecs_task_definition.worker.arn
  desired_count    = var.worker_desired_count
  launch_type      = "FARGATE"
  platform_version = "LATEST"

  network_configuration {
    subnets          = aws_subnet.private[*].id
    security_groups  = [aws_security_group.worker.id]
    assign_public_ip = false
  }

  service_registries {
    registry_arn = aws_service_discovery_service.worker.arn
  }

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  deployment_minimum_healthy_percent = 0
  deployment_maximum_percent         = 200

  depends_on = [aws_iam_role_policy.execution_secrets]
}
