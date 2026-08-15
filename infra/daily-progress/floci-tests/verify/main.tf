terraform {
  required_version = ">= 1.6.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 4.0"
    }
  }
}

variable "aws_endpoint_url" {
  type = string
}

variable "aws_region" {
  type = string
}

variable "bucket_name" {
  type = string
}

variable "collection_timezone" {
  type = string
}

variable "lambda_image_uri" {
  type = string
}

variable "object_prefix" {
  type = string
}

variable "role_arn" {
  type = string
}

variable "role_name" {
  type = string
}

variable "secret_arn" {
  type = string
}

provider "aws" {
  region                      = var.aws_region
  access_key                  = "test"
  secret_key                  = "test"
  s3_use_path_style           = true
  skip_credentials_validation = true
  skip_metadata_api_check     = true
  skip_region_validation      = true

  endpoints {
    cloudwatchevents = var.aws_endpoint_url
    iam              = var.aws_endpoint_url
    lambda           = var.aws_endpoint_url
    s3               = var.aws_endpoint_url
    secretsmanager   = var.aws_endpoint_url
    sns              = var.aws_endpoint_url
    sts              = var.aws_endpoint_url
  }
}

resource "aws_sns_topic" "results" {
  name                        = "daily-progress-e2e-results.fifo"
  fifo_topic                  = true
  content_based_deduplication = true
}

resource "aws_iam_role_policy" "probe" {
  name = "daily-progress-e2e-probe-runtime"
  role = var.role_name

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "logs:CreateLogGroup",
        "logs:CreateLogStream",
        "logs:PutLogEvents",
        "sns:Publish",
      ]
      Resource = "*"
    }]
  })
}

resource "aws_lambda_function" "probe" {
  function_name = "daily-progress-e2e-probe"
  role          = var.role_arn
  package_type  = "Image"
  image_uri     = var.lambda_image_uri
  timeout       = 30
  memory_size   = 256

  environment {
    variables = {
      DAILY_PROGRESS_BUCKET        = var.bucket_name
      DAILY_PROGRESS_PREFIX        = var.object_prefix
      DAILY_PROGRESS_TIMEZONE      = var.collection_timezone
      PROGRESS_COLLECTOR_SECRET_ID = var.secret_arn
      SNS_TOPIC_ARN                = aws_sns_topic.results.arn
    }
  }

  depends_on = [aws_iam_role_policy.probe]
}

resource "aws_cloudwatch_event_rule" "schedule" {
  name                = "daily-progress-e2e-probe-schedule"
  schedule_expression = "cron(0 10 * * ? *)"
}

resource "aws_cloudwatch_event_target" "probe" {
  rule      = aws_cloudwatch_event_rule.schedule.name
  target_id = "daily-progress-e2e-probe"
  arn       = aws_lambda_function.probe.arn
}

resource "aws_lambda_permission" "eventbridge" {
  statement_id  = "AllowEventBridgeInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.probe.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.schedule.arn
}

resource "aws_secretsmanager_secret_version" "probe" {
  secret_id     = var.secret_arn
  secret_string = "daily-progress-e2e-sentinel"
}

data "aws_lambda_invocation" "probe" {
  function_name = aws_lambda_function.probe.function_name
  input         = jsonencode({ source = "terraform-e2e" })

  depends_on = [
    aws_lambda_permission.eventbridge,
    aws_secretsmanager_secret_version.probe,
  ]
}

data "aws_s3_object" "probe" {
  bucket = var.bucket_name
  key    = "${var.object_prefix}/probe.json"

  depends_on = [data.aws_lambda_invocation.probe]
}

data "aws_lambda_function" "probe" {
  function_name = aws_lambda_function.probe.function_name

  depends_on = [data.aws_lambda_invocation.probe]
}

output "invocation_result" {
  value = data.aws_lambda_invocation.probe.result
}

output "lambda_environment" {
  value = data.aws_lambda_function.probe.environment[0].variables
}

output "object_body" {
  value = data.aws_s3_object.probe.body
}

output "object_content_type" {
  value = data.aws_s3_object.probe.content_type
}

output "schedule_expression" {
  value = aws_cloudwatch_event_rule.schedule.schedule_expression
}

output "schedule_target_arn" {
  value = aws_cloudwatch_event_target.probe.arn
}

output "sns_topic_arn" {
  value = aws_sns_topic.results.arn
}
