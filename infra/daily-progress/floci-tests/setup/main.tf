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

provider "aws" {
  region                      = var.aws_region
  access_key                  = "test"
  secret_key                  = "test"
  skip_credentials_validation = true
  skip_metadata_api_check     = true
  skip_region_validation      = true

  endpoints {
    iam = var.aws_endpoint_url
    sts = var.aws_endpoint_url
  }
}

resource "aws_iam_role" "probe" {
  name = "daily-progress-e2e-probe-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = "sts:AssumeRole"
      Principal = {
        Service = "lambda.amazonaws.com"
      }
    }]
  })
}

output "role_arn" {
  value = aws_iam_role.probe.arn
}

output "role_name" {
  value = aws_iam_role.probe.name
}
