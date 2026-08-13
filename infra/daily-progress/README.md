# Daily progress infrastructure

This directory publishes and deploys a scheduled AWS Lambda that collects the previous complete
calendar day from GitHub, Linear, and Google Calendar. It writes the versioned
`progress-collector` document to:

```text
s3://BUCKET/progress/YYYY-MM-DD/progress.json
```

The object prefix is configurable. Re-running the Lambda for the same collection day writes the
same key; S3 bucket versioning retains every earlier attempt.

The deployment uses the upstream `lambdacron` Terraform modules and Python package directly from
their canonical Git repository. No lambdacron code is vendored here.

## Prerequisites

- OpenTofu 1.6 or newer
- AWS CLI credentials able to manage ECR Public, ECR, Lambda, EventBridge, SNS, S3, IAM, and
  Secrets Manager
- Docker with Buildx
- A complete portable authentication file created by `collect-progress-auth`

Check the authentication file before deployment:

```shell
collect-progress-auth status
collect-progress-auth path
```

The file must contain credentials for `github`, `linear`, and `google_calendar`. Keep it outside
the repository and treat it like a password.

## 1. Publish the Lambda image

The image-publication root must run separately because public ECR repositories are managed in
`us-east-1`.

```shell
cd infra/daily-progress/lambda
cp terraform.tfvars.example terraform.tfvars
tofu init
tofu plan
tofu apply
tofu output -raw repository_url
```

The Docker build context is the repository root so the image can install
`packages/progress-collector` as a normal Python package. The tracked `.dockerignore` excludes
Git metadata, local environments, caches, Terraform state, and local tfvars from that context.

## 2. Deploy the scheduled job

Copy the example configuration and set `lambda_public_repo_url` to the `repository_url` output
from the image-publication root. Review every plan before applying it.

```shell
cd infra/daily-progress
cp terraform.tfvars.example terraform.tfvars
tofu init
tofu plan
tofu apply
```

By default, AWS generates a globally unique bucket name beginning with `daily-progress-`. Set
`bucket_name` only when an explicit globally unique name is required. The bucket has versioning,
SSE-S3 encryption, bucket-owner enforcement, and all public access blocked. Terraform will not
force-delete a non-empty bucket.

The default schedule is `cron(0 10 * * ? *)`. EventBridge evaluates this in UTC, so it runs at
4:00 AM Chicago time during CST and 5:00 AM during CDT. `collection_timezone` controls the day
boundaries but does not change the UTC schedule; coordinate `schedule_expression` yourself when
using another timezone.

## 3. Populate the credential secret

Terraform creates the Secrets Manager container but deliberately does not put a secret value in
Terraform configuration or state. After the first deployment, upload the existing portable auth
document:

```shell
AUTH_CONFIG_PATH="$(collect-progress-auth path)"
SECRET_ARN="$(tofu output -raw progress_collector_secret_arn)"
aws secretsmanager put-secret-value \
  --secret-id "${SECRET_ARN}" \
  --secret-string "file://${AUTH_CONFIG_PATH}"
```

Credential rotation uses the same `put-secret-value` operation. The Lambda fetches the current
secret value on every invocation, writes it temporarily with private POSIX permissions, loads the
three source configurations, and removes the temporary file before collection.

## Results and failures

The Lambda persists successful and partial collection documents. If an individual provider fails,
the JSON retains that source's safe structured error and lambdacron publishes a
`DAILY_PROGRESS_PARTIAL` result. Complete runs publish `DAILY_PROGRESS_COLLECTED`. SNS messages
contain storage metadata, item counts, and failed source names only; they never contain collected
activities or credentials.

Failures that prevent configuration, credential loading, or S3 persistence fail the Lambda
invocation. Lambdacron creates the SNS results topic, but this project intentionally configures no
email, print, or other notification consumer.

## Validation

From the repository root:

```shell
pixi run -e dev python -m pytest packages/progress-collector/tests infra/daily-progress/tests
pixi run -e dev ruff check packages/progress-collector infra/daily-progress
tofu -chdir=infra/daily-progress fmt -check -recursive
tofu -chdir=infra/daily-progress init -backend=false
tofu -chdir=infra/daily-progress validate
tofu -chdir=infra/daily-progress/lambda init -backend=false
tofu -chdir=infra/daily-progress/lambda validate
docker buildx build --platform linux/amd64 \
  -f infra/daily-progress/lambda/docker/Dockerfile .
```

No remote state backend or deployment automation is defined here. Choose and configure a backend
appropriate for the AWS account before using this in an automated deployment.
