locals {
  application_name           = "daily-progress"
  tags                       = merge({ managed_by = local.application_name }, var.tags)
  object_prefix              = trim(var.object_prefix, "/")
  secret_name                = coalesce(var.secret_name, "${local.application_name}-auth-${terraform.workspace}")
  scheduled_lambda_role_name = trimprefix(module.lambdacron.scheduled_lambda_role_arn, "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/")
  lambda_env = merge(var.lambda_env, {
    DAILY_PROGRESS_BUCKET        = aws_s3_bucket.progress.bucket
    DAILY_PROGRESS_PREFIX        = local.object_prefix
    DAILY_PROGRESS_TIMEZONE      = var.collection_timezone
    PROGRESS_COLLECTOR_SECRET_ID = aws_secretsmanager_secret.progress_collector.arn
  })
}

data "aws_caller_identity" "current" {}

provider "aws" {
  region = var.aws_region
}

resource "aws_s3_bucket" "progress" {
  bucket        = var.bucket_name
  bucket_prefix = var.bucket_name == null ? "daily-progress-" : null
  force_destroy = false

  tags = local.tags
}

resource "aws_s3_bucket_public_access_block" "progress" {
  bucket = aws_s3_bucket.progress.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "progress" {
  bucket = aws_s3_bucket.progress.id

  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "progress" {
  bucket = aws_s3_bucket.progress.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_versioning" "progress" {
  bucket = aws_s3_bucket.progress.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_secretsmanager_secret" "progress_collector" {
  name                    = local.secret_name
  description             = "Portable progress-collector credentials for the daily progress Lambda."
  recovery_window_in_days = 30

  tags = local.tags
}

module "lambda_image_republish" {
  source = "git::https://github.com/omsf/lambdacron.git//modules/lambda-image-republish"

  source_lambda_repo = var.lambda_public_repo_url
  source_lambda_tag  = var.lambda_public_tag

  destination_repository_name = var.lambda_private_repository_name
  enable_kms_encryption       = var.lambda_enable_kms_encryption
  kms_key_arn                 = var.lambda_kms_key_arn

  tags = local.tags
}

module "lambdacron" {
  source = "git::https://github.com/omsf/lambdacron.git"

  aws_region                  = var.aws_region
  lambda_image_uri            = module.lambda_image_republish.lambda_image_uri_with_digest
  schedule_expression         = var.schedule_expression
  topic_name                  = var.topic_name
  fifo_topic                  = true
  content_based_deduplication = true

  lambda_env      = local.lambda_env
  timeout         = var.lambda_timeout
  memory_size     = var.lambda_memory_size
  lambda_name     = var.lambda_name
  image_command   = var.lambda_image_command
  create_test_url = false

  tags = local.tags
}

data "aws_iam_policy_document" "scheduled_lambda_storage" {
  statement {
    sid       = "WriteDailyProgress"
    effect    = "Allow"
    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.progress.arn}/${local.object_prefix}/*"]
  }

  statement {
    sid       = "ReadProgressCollectorCredentials"
    effect    = "Allow"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [aws_secretsmanager_secret.progress_collector.arn]
  }
}

resource "aws_iam_policy" "scheduled_lambda_storage" {
  name   = "${local.application_name}-storage-${terraform.workspace}"
  policy = data.aws_iam_policy_document.scheduled_lambda_storage.json
  tags   = local.tags
}

resource "aws_iam_role_policy_attachment" "scheduled_lambda_storage" {
  role       = local.scheduled_lambda_role_name
  policy_arn = aws_iam_policy.scheduled_lambda_storage.arn
}
