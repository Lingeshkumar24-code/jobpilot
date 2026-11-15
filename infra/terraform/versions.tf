terraform {
  required_version = ">= 1.6.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.70"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }

  # Configure remote state before the first real apply, for example:
  #
  # backend "s3" {
  #   bucket         = "your-terraform-state-bucket"
  #   key            = "jobpilot/terraform.tfstate"
  #   region         = "ap-south-1"
  #   dynamodb_table = "terraform-locks"
  #   encrypt        = true
  # }
}
