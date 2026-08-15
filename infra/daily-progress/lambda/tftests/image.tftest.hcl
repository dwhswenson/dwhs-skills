mock_provider "aws" {
  alias = "test"
}

mock_provider "null" {}

override_data {
  target = module.lambda_image_public.data.aws_region.current

  values = {
    name = "us-east-1"
  }
}

override_resource {
  target = module.lambda_image_public.aws_ecrpublic_repository.image

  values = {
    arn            = "arn:aws:ecr-public::123456789012:repository/daily-progress-lambdacron"
    repository_uri = "public.ecr.aws/example/daily-progress-lambdacron"
  }
}

run "default_public_image_contract" {
  command = plan

  providers = {
    aws.use1 = aws.test
  }

  assert {
    condition     = output.repository_arn == "arn:aws:ecr-public::123456789012:repository/daily-progress-lambdacron"
    error_message = "The public repository ARN must be forwarded from the image module."
  }

  assert {
    condition     = output.repository_url == "public.ecr.aws/example/daily-progress-lambdacron"
    error_message = "The public repository URL must be forwarded from the image module."
  }

  assert {
    condition     = output.image_uri == "public.ecr.aws/example/daily-progress-lambdacron:latest"
    error_message = "The default public image must use the latest tag."
  }
}

run "custom_public_image_contract" {
  command = plan

  providers = {
    aws.use1 = aws.test
  }

  variables {
    repository_name = "custom-daily-progress"
    image_tag       = "release-2026-08"
    platform        = "linux/arm64"
    tags = {
      environment = "test"
    }
  }

  assert {
    condition     = output.image_uri == "public.ecr.aws/example/daily-progress-lambdacron:release-2026-08"
    error_message = "A caller-supplied image tag must be reflected in the published image URI."
  }
}
