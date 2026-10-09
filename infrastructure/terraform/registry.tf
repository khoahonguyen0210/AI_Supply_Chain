locals {
  images = toset(["scm-backend", "scm-ml", "scm-frontend"])
}

resource "aws_ecr_repository" "image" {
  for_each             = local.images
  name                 = "${local.name}/${each.key}"
  image_tag_mutability = "IMMUTABLE_WITH_EXCLUSION"

  # `main` and `latest` move; release and sha-<commit> tags never do
  image_tag_mutability_exclusion_filter {
    filter      = "main"
    filter_type = "WILDCARD"
  }

  image_tag_mutability_exclusion_filter {
    filter      = "latest"
    filter_type = "WILDCARD"
  }

  image_scanning_configuration {
    scan_on_push = true
  }

  encryption_configuration {
    encryption_type = "AES256"
  }
}

resource "aws_ecr_lifecycle_policy" "image" {
  for_each   = aws_ecr_repository.image
  repository = each.value.name
  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep the 30 most recent sha- builds"
      selection = {
        tagStatus     = "tagged"
        tagPrefixList = ["sha-"]
        countType     = "imageCountMoreThan"
        countNumber   = 30
      }
      action = { type = "expire" }
      }, {
      rulePriority = 2
      description  = "Drop untagged layers after a week"
      selection = {
        tagStatus   = "untagged"
        countType   = "sinceImagePushed"
        countUnit   = "days"
        countNumber = 7
      }
      action = { type = "expire" }
    }]
  })
}
