resource "aws_db_subnet_group" "main" {
  name       = "${local.name}-db"
  subnet_ids = aws_subnet.private[*].id
}

resource "aws_db_parameter_group" "main" {
  name   = "${local.name}-pg16"
  family = "postgres16"

  parameter {
    name  = "log_min_duration_statement"
    value = "1000"
  }

  parameter {
    name  = "rds.force_ssl"
    value = "1"
  }
}

resource "aws_db_instance" "main" {
  identifier     = "${local.name}-db"
  engine         = "postgres"
  engine_version = "16"
  instance_class = var.db_instance_class

  db_name  = var.db_name
  username = var.db_username
  password = var.db_password
  port     = 5432

  allocated_storage     = 20
  max_allocated_storage = 100
  storage_type          = "gp3"
  storage_encrypted     = true

  db_subnet_group_name   = aws_db_subnet_group.main.name
  vpc_security_group_ids = [aws_security_group.database.id]
  parameter_group_name   = aws_db_parameter_group.main.name
  publicly_accessible    = false

  multi_az                   = false
  backup_retention_period    = 7
  backup_window              = "18:00-19:00"
  maintenance_window         = "sun:19:00-sun:20:00"
  auto_minor_version_upgrade = true
  copy_tags_to_snapshot      = true
  deletion_protection        = var.rds_deletion_protection
  skip_final_snapshot        = false
  final_snapshot_identifier  = "${local.name}-final"

  enabled_cloudwatch_logs_exports = ["postgresql"]
  performance_insights_enabled    = false

  apply_immediately = false
}
