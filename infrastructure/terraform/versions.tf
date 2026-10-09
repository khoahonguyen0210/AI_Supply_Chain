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

  # A real deployment would add a remote state backend here (S3 with use_lockfile = true).
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
