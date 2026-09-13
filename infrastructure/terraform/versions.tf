# AWS mapping of the local stack. Validated with `terraform validate`; never applied by this
# project (no AWS account is needed to build, test or run it). See docs/cloud.md.
terraform {
  required_version = ">= 1.11"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.67"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.9"
    }
  }

  # A real deployment keeps state remotely, for example:
  # backend "s3" {
  #   bucket       = "<state bucket>"
  #   key          = "scm/terraform.tfstate"
  #   region       = "us-east-1"
  #   use_lockfile = true
  # }
}

provider "aws" {
  region = var.region

  default_tags {
    tags = {
      Project     = "scm-platform"
      Environment = var.environment
      ManagedBy   = "terraform"
    }
  }
}
