locals {
  tags                 = merge({ managed_by = "daily-progress" }, var.tags)
  repository_root      = abspath("${path.module}/../../..")
  lambda_source_dir    = "${path.module}/docker"
  progress_package_dir = "${local.repository_root}/packages/progress-collector"
  dockerfile_path      = "${local.lambda_source_dir}/Dockerfile"
}

provider "aws" {
  alias  = "use1"
  region = "us-east-1"
}

module "lambda_image_public" {
  source = "git::https://github.com/omsf/lambdacron.git//modules/lambda-image-public"

  providers = {
    aws = aws.use1
  }

  repository_name = var.repository_name
  image_tag       = var.image_tag
  platform        = var.platform

  short_description = "Daily GitHub, Linear, and Google Calendar progress collection Lambda."
  about_text        = "Public image for the daily-progress lambdacron job."
  usage_text        = "Publish this image separately, then configure the daily-progress deployment root to republish it into private ECR."

  build_context       = local.repository_root
  dockerfile_path     = local.dockerfile_path
  build_context_paths = [local.lambda_source_dir, local.progress_package_dir]
  build_context_patterns = [
    "**",
  ]

  architectures     = ["x86-64"]
  operating_systems = ["Linux"]
  tags              = local.tags
}
