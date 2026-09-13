variable "region" {
  description = "AWS region."
  type        = string
  default     = "us-east-1"
}

variable "environment" {
  description = "Environment name, used in resource names."
  type        = string
  default     = "demo"
}

variable "image_tag" {
  description = "Tag of the three images in ECR (CI pushes sha-<commit> and release versions)."
  type        = string
  default     = "main"
}

variable "vpc_cidr" {
  description = "CIDR of the VPC; split into two public and two private subnets."
  type        = string
  default     = "10.40.0.0/16"
}

variable "single_nat_gateway" {
  description = "One NAT gateway for both AZs (cheaper, not zone-redundant)."
  type        = bool
  default     = true
}

variable "certificate_arn" {
  description = "ACM certificate for HTTPS on the load balancer. Empty: HTTP only (demo)."
  type        = string
  default     = ""
}

variable "allowed_cidrs" {
  description = "Client CIDRs allowed to reach the load balancer."
  type        = list(string)
  default     = ["0.0.0.0/0"]
}

variable "db_instance_class" {
  description = "RDS instance class."
  type        = string
  default     = "db.t4g.medium"
}

variable "db_allocated_storage_gb" {
  description = "RDS storage (gp3)."
  type        = number
  default     = 20
}

variable "db_multi_az" {
  description = "Standby replica in a second AZ."
  type        = bool
  default     = false
}

variable "credentials_version" {
  description = "Bump to generate and write new database and application secrets."
  type        = number
  default     = 1
}

variable "worker_min" {
  description = "Minimum number of worker tasks (queue worker + engine sidecar)."
  type        = number
  default     = 1
}

variable "worker_max" {
  description = "Maximum number of worker tasks."
  type        = number
  default     = 4
}

variable "planner" {
  description = "Copilot planner: rule (offline, default) or claude (needs the anthropic_api_key secret set)."
  type        = string
  default     = "rule"

  validation {
    condition     = contains(["rule", "claude"], var.planner)
    error_message = "planner must be rule or claude."
  }
}

variable "log_retention_days" {
  description = "CloudWatch log retention."
  type        = number
  default     = 30
}

variable "alarm_email" {
  description = "Email subscribed to the alarm topic. Empty: no subscription."
  type        = string
  default     = ""
}

variable "github_repository" {
  description = "owner/name allowed to push images to ECR through GitHub OIDC. Empty: no CI role."
  type        = string
  default     = ""
}
