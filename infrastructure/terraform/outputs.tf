output "url" {
  description = "Public address of the frontend."
  value       = "${var.certificate_arn == "" ? "http" : "https"}://${aws_lb.main.dns_name}"
}

output "ecr_repositories" {
  description = "Image name -> ECR repository URL (push <url>:<tag>)."
  value       = { for name, repo in aws_ecr_repository.image : name => repo.repository_url }
}

output "database_endpoint" {
  description = "PostgreSQL address inside the VPC."
  value       = aws_db_instance.postgres.address
}

output "artifact_bucket" {
  description = "S3 bucket for model and evaluation artifacts."
  value       = aws_s3_bucket.artifacts.bucket
}

output "app_secret_arn" {
  description = "Secrets Manager secret holding the generated credentials (demo password included)."
  value       = aws_secretsmanager_secret.app.arn
}

output "ci_role_arn" {
  description = "Role GitHub Actions assumes to push images (empty without github_repository)."
  value       = var.github_repository == "" ? "" : aws_iam_role.ci[0].arn
}

output "seed_command" {
  description = "Loads the synthetic world once the backend has run its migrations."
  value = join(" ", [
    "aws ecs run-task --cluster ${aws_ecs_cluster.main.name}",
    "--task-definition ${aws_ecs_task_definition.seed.family} --launch-type FARGATE",
    "--network-configuration 'awsvpcConfiguration={subnets=[${join(",", aws_subnet.private[*].id)}],securityGroups=[${aws_security_group.tasks.id}]}'",
  ])
}
