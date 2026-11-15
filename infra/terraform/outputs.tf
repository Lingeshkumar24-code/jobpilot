output "alb_dns_name" {
  description = "Public ALB DNS name."
  value       = aws_lb.main.dns_name
}

output "app_url" {
  description = "Application URL (uses the public origin when HTTPS is configured)."
  value       = var.acm_certificate_arn == "" ? "http://${aws_lb.main.dns_name}" : var.public_origin
}

output "ecr_repositories" {
  description = "ECR repository URLs keyed by service."
  value       = { for key, repo in aws_ecr_repository.this : key => repo.repository_url }
}

output "database_endpoint" {
  description = "RDS endpoint (host:port)."
  value       = "${aws_db_instance.main.address}:${aws_db_instance.main.port}"
  sensitive   = true
}

output "resume_bucket" {
  value = aws_s3_bucket.resumes.bucket
}

output "ssm_parameter_names" {
  description = "SecureString parameter names consumed by ECS."
  value       = [for parameter in aws_ssm_parameter.secrets : parameter.name]
}
