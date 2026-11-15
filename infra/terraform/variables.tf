variable "project" {
  description = "Short project name used in resource names."
  type        = string
  default     = "jobpilot"
}

variable "environment" {
  description = "Deployment environment (staging, prod)."
  type        = string
  default     = "prod"
}

variable "aws_region" {
  description = "AWS region."
  type        = string
  default     = "ap-south-1"
}

variable "vpc_cidr" {
  description = "CIDR for the VPC."
  type        = string
  default     = "10.40.0.0/16"
}

variable "db_instance_class" {
  description = "RDS instance class. db.t4g.micro is the cheapest useful starting point."
  type        = string
  default     = "db.t4g.micro"
}

variable "db_name" {
  description = "PostgreSQL database name."
  type        = string
  default     = "jobpilot"
}

variable "db_username" {
  description = "PostgreSQL master user."
  type        = string
  default     = "jobpilot"
}

variable "db_password" {
  description = "PostgreSQL master password (at least 16 characters)."
  type        = string
  sensitive   = true
  validation {
    condition     = length(var.db_password) >= 16
    error_message = "db_password must be at least 16 characters."
  }
}

variable "jwt_secret" {
  description = "JWT signing secret (at least 32 characters)."
  type        = string
  sensitive   = true
  validation {
    condition     = length(var.jwt_secret) >= 32
    error_message = "jwt_secret must be at least 32 characters."
  }
}

variable "approval_signing_secret" {
  description = "HMAC secret shared by the API and the browser worker (at least 32 characters)."
  type        = string
  sensitive   = true
  validation {
    condition     = length(var.approval_signing_secret) >= 32
    error_message = "approval_signing_secret must be at least 32 characters."
  }
}

variable "browser_worker_secret" {
  description = "Shared secret for calls to the browser worker (at least 24 characters)."
  type        = string
  sensitive   = true
  validation {
    condition     = length(var.browser_worker_secret) >= 24
    error_message = "browser_worker_secret must be at least 24 characters."
  }
}

variable "n8n_webhook_secret" {
  description = "HMAC secret for n8n inbound webhooks (at least 24 characters)."
  type        = string
  sensitive   = true
  validation {
    condition     = length(var.n8n_webhook_secret) >= 24
    error_message = "n8n_webhook_secret must be at least 24 characters."
  }
}

variable "public_origin" {
  description = "Browser origin of the deployed frontend, e.g. https://app.example.com. Used for CORS and cookie policy."
  type        = string
  validation {
    condition     = can(regex("^https?://", var.public_origin))
    error_message = "public_origin must start with http:// or https://."
  }
}

variable "acm_certificate_arn" {
  description = "Optional ACM certificate ARN for HTTPS. Without it the ALB serves HTTP only (not recommended for production)."
  type        = string
  default     = ""
}

variable "image_tag" {
  description = "Container image tag to deploy. The deploy workflow pushes both the commit SHA and latest."
  type        = string
  default     = "latest"
}

variable "backend_cpu" {
  type    = number
  default = 512
}

variable "backend_memory" {
  type    = number
  default = 1024
}

variable "frontend_cpu" {
  type    = number
  default = 256
}

variable "frontend_memory" {
  type    = number
  default = 512
}

variable "worker_cpu" {
  type    = number
  default = 1024
}

variable "worker_memory" {
  type    = number
  default = 2048
}

variable "worker_desired_count" {
  description = "Browser worker task count. Keep at 0 when idle; scale up on demand."
  type        = number
  default     = 0
}

variable "rds_deletion_protection" {
  type    = bool
  default = true
}

variable "log_retention_days" {
  type    = number
  default = 30
}

variable "alarm_email" {
  description = "Optional email for CloudWatch alarms."
  type        = string
  default     = ""
}
