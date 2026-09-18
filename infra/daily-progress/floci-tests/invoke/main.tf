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

variable "lambda_name" {
  type = string
}

variable "secret_arn" {
  type = string
}

provider "aws" {
  region                      = var.aws_region
  access_key                  = "test"
  secret_key                  = "test"
  skip_credentials_validation = true
  skip_metadata_api_check     = true
  skip_region_validation      = true

  endpoints {
    lambda         = var.aws_endpoint_url
    secretsmanager = var.aws_endpoint_url
    sts            = var.aws_endpoint_url
  }
}

resource "aws_secretsmanager_secret_version" "probe" {
  secret_id     = var.secret_arn
  secret_string = "daily-progress-e2e-sentinel"
}

data "aws_lambda_invocation" "probe" {
  function_name = var.lambda_name
  input         = jsonencode({ source = "terraform-e2e" })

  depends_on = [aws_secretsmanager_secret_version.probe]
}

output "invocation_result" {
  value = data.aws_lambda_invocation.probe.result
}
