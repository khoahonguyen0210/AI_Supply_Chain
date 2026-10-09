# Write-only arguments keep generated secrets out of state; bump var.credentials_version to rotate.
ephemeral "random_password" "db" {
  length  = 32
  special = false
}

ephemeral "random_password" "jwt" {
  length  = 48
  special = false
}

ephemeral "random_password" "internal_token" {
  length  = 32
  special = false
}

ephemeral "random_password" "demo" {
  length  = 16
  special = false
}

resource "aws_secretsmanager_secret" "app" {
  name                    = "${local.name}/app"
  description             = "Database password, JWT signing key, backend-engine token, demo password"
  recovery_window_in_days = 7
}

resource "aws_secretsmanager_secret_version" "app" {
  secret_id = aws_secretsmanager_secret.app.id
  secret_string_wo = jsonencode({
    POSTGRES_PASSWORD     = ephemeral.random_password.db.result
    SCM_JWT_SECRET        = ephemeral.random_password.jwt.result
    SCM_ML_INTERNAL_TOKEN = ephemeral.random_password.internal_token.result
    SCM_DEMO_PASSWORD     = ephemeral.random_password.demo.result
  })
  secret_string_wo_version = var.credentials_version
}

# Only read when var.planner = "claude"; set it with aws secretsmanager put-secret-value.
resource "aws_secretsmanager_secret" "anthropic" {
  name                    = "${local.name}/anthropic"
  description             = "ANTHROPIC_API_KEY for the Claude planner (optional)"
  recovery_window_in_days = 7
}

resource "aws_db_subnet_group" "main" {
  name       = local.name
  subnet_ids = aws_subnet.private[*].id
}

resource "aws_db_parameter_group" "postgres" {
  name   = "${local.name}-pg16"
  family = "postgres16"

  parameter {
    name  = "rds.force_ssl"
    value = "1"
  }

  parameter {
    name  = "log_min_duration_statement"
    value = "500"
  }
}

# pgvector ships with RDS PostgreSQL 16; the backend migration V2 runs CREATE EXTENSION vector.
resource "aws_db_instance" "postgres" {
  identifier                   = local.name
  engine                       = "postgres"
  engine_version               = "16"
  instance_class               = var.db_instance_class
  allocated_storage            = var.db_allocated_storage_gb
  max_allocated_storage        = var.db_allocated_storage_gb * 5
  storage_type                 = "gp3"
  storage_encrypted            = true
  db_name                      = "scm"
  username                     = "scm"
  password_wo                  = ephemeral.random_password.db.result
  password_wo_version          = var.credentials_version
  db_subnet_group_name         = aws_db_subnet_group.main.name
  vpc_security_group_ids       = [aws_security_group.data.id]
  parameter_group_name         = aws_db_parameter_group.postgres.name
  multi_az                     = var.db_multi_az
  publicly_accessible          = false
  backup_retention_period      = 7
  deletion_protection          = true
  skip_final_snapshot          = false
  final_snapshot_identifier    = "${local.name}-final"
  performance_insights_enabled = true
  auto_minor_version_upgrade   = true
}

resource "aws_s3_bucket" "artifacts" {
  bucket_prefix = "${local.name}-artifacts-"
}

resource "aws_s3_bucket_versioning" "artifacts" {
  bucket = aws_s3_bucket.artifacts.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "artifacts" {
  bucket = aws_s3_bucket.artifacts.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "artifacts" {
  bucket                  = aws_s3_bucket.artifacts.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_lifecycle_configuration" "artifacts" {
  bucket = aws_s3_bucket.artifacts.id
  rule {
    id     = "old-versions"
    status = "Enabled"
    filter {}
    noncurrent_version_expiration {
      noncurrent_days = 90
    }
  }
}

resource "aws_efs_file_system" "engine_state" {
  encrypted = true
  tags      = { Name = "${local.name}-engine-state" }
}

resource "aws_efs_mount_target" "engine_state" {
  count           = length(aws_subnet.private)
  file_system_id  = aws_efs_file_system.engine_state.id
  subnet_id       = aws_subnet.private[count.index].id
  security_groups = [aws_security_group.data.id]
}

resource "aws_efs_access_point" "engine_state" {
  file_system_id = aws_efs_file_system.engine_state.id
  posix_user {
    uid = 10001
    gid = 10001
  }
  root_directory {
    path = "/scm"
    creation_info {
      owner_uid   = 10001
      owner_gid   = 10001
      permissions = "0750"
    }
  }
}
