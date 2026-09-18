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
pixi run -e dev terraform-format
pixi run -e dev terraform-validate
pixi run -e dev terraform-test
pixi run -e dev terraform-test-floci
docker buildx build --platform linux/amd64 \
  -f infra/daily-progress/lambda/docker/Dockerfile .
```

`terraform-test` runs isolated OpenTofu contract tests for both Terraform roots. The tests use
mock providers and module/resource overrides, so they neither contact AWS nor execute Docker build
or image-publication commands. They verify the storage protections, IAM policy inputs, tags,
outputs, variable validation, and public-image configuration.

`terraform-test-floci` is the explicit Docker-backed E2E layer. It requires a working Docker
engine whose socket permits Floci to start sibling ECR and Lambda containers. It starts the pinned
`floci/floci:2.1.0` image with fixed fake credentials, publishes a small `linux/amd64` probe image
to Floci's private ECR, and runs `tofu test` against the scheduled deployment. The probe reads a
sentinel from the Terraform-created secret, writes metadata-only JSON to the protected bucket, and
publishes a metadata-only result to SNS. The runner destroys the OpenTofu test resources, stops
Floci, and removes the local probe image even on failure. Ordinary Python and native Terraform
tasks never start Docker. The disposable test bucket sets `bucket_force_destroy = true` so the
probe object is removed during teardown; the production default remains `false`.

The E2E test has two narrowly scoped Floci compatibility overrides. Floci 2.1.0 does not emulate
ECR Public, so the image-republish module is overridden with the probe pre-seeded in Floci's
private ECR using its digest-qualified URI. Floci also does not implement S3's ownership-controls
API, so that resource is
overridden while the remaining bucket protections are applied. Lambdacron inherits the
endpoint-configured AWS provider and its real Lambda, IAM, EventBridge, and SNS resources are
applied and verified.

Docker Desktop 4.14.0 (Docker Engine 20.10.21) is known to reject the localhost image pulls Floci
uses for Lambda execution. Upgrade Docker Desktop if the E2E task fails with an `unknown image`
error from the Docker `/images/create` API.

The path-filtered `daily-progress Floci E2E` GitHub Actions workflow runs the same explicit Floci
task on an Ubuntu Docker runner for changes to this infrastructure, its root Pixi environment, or
the workflow itself. It can also be started manually with `workflow_dispatch`.

No real AWS credentials are read by the Floci runner. The E2E probe intentionally verifies only
infrastructure wiring; the existing Python suite remains responsible for GitHub, Linear, Google,
and collector behavior. Floci's default IAM mode is not AWS-grade policy enforcement, so the native
contract tests remain authoritative for the exact IAM document.

No remote state backend or deployment automation is defined here. Choose and configure a backend
appropriate for the AWS account before using this in an automated deployment.
