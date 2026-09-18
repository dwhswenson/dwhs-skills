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

variable "lambda_name" {
  type = string
}

variable "invocation_result" {
  type = string
}

variable "object_prefix" {
  type = string
}

variable "secret_arn" {
  type = string
}

variable "sns_topic_arn" {
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

data "aws_s3_object" "probe" {
  bucket = var.bucket_name
  key    = "${var.object_prefix}/probe.json"
}

data "aws_lambda_function" "probe" {
  function_name = var.lambda_name
}

output "invocation_result" {
  value = var.invocation_result
}

output "lambda_environment" {
  value = data.aws_lambda_function.probe.environment[0].variables
}

output "lambda_arn" {
  value = data.aws_lambda_function.probe.arn
}

output "object_body" {
  value = data.aws_s3_object.probe.body
}

output "object_content_type" {
  value = data.aws_s3_object.probe.content_type
}

output "sns_topic_arn" {
  value = var.sns_topic_arn
}

output "secret_arn" {
  value = var.secret_arn
}
