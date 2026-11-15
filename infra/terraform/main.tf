provider "aws" {
  region = var.aws_region

  default_tags {
    tags = local.tags
  }
}

data "aws_caller_identity" "current" {}
data "aws_availability_zones" "available" {
  state = "available"
}

locals {
  name = "${var.project}-${var.environment}"
  azs  = slice(data.aws_availability_zones.available.names, 0, 2)

  tags = {
    Project     = var.project
    Environment = var.environment
    ManagedBy   = "terraform"
    Application = "jobpilot-ai"
  }

  repositories = {
    backend          = "jobpilot-backend"
    frontend         = "jobpilot-frontend"
    "browser-worker" = "jobpilot-browser-worker"
  }
}
