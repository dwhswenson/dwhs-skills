"""Run the Docker-backed daily-progress infrastructure test against Floci."""

from __future__ import annotations

import base64
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import boto3
import docker
from botocore.config import Config
from botocore.exceptions import ClientError
from floci import FlociContainer


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
TERRAFORM_ROOT = REPOSITORY_ROOT / "infra" / "daily-progress"
PROBE_CONTEXT = TERRAFORM_ROOT / "floci-tests" / "probe"
FLOCI_IMAGE = "floci/floci:1.6.0"
PROBE_REPOSITORY = "daily-progress-e2e-probe"
PROBE_TAG = "test"


def aws_client(service: str, endpoint: str):
    return boto3.client(
        service,
        endpoint_url=endpoint,
        region_name="us-east-1",
        aws_access_key_id="test",
        aws_secret_access_key="test",
        config=Config(retries={"max_attempts": 3, "mode": "standard"}),
    )


def clean_environment(endpoint: str) -> dict[str, str]:
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("AWS_") and not key.startswith("TF_VAR_")
    }
    environment.update(
        {
            "AWS_ACCESS_KEY_ID": "test",
            "AWS_DEFAULT_REGION": "us-east-1",
            "AWS_EC2_METADATA_DISABLED": "true",
            "AWS_ENDPOINT_URL": endpoint,
            "AWS_REGION": "us-east-1",
            "AWS_SECRET_ACCESS_KEY": "test",
        }
    )
    return environment


def push_probe_image(docker_client, endpoint: str, image_tags: list[str]) -> str:
    ecr = aws_client("ecr", endpoint)
    try:
        repository = ecr.create_repository(repositoryName=PROBE_REPOSITORY)["repository"]
    except ClientError as exc:
        message = exc.response.get("Error", {}).get("Message", "")
        if "Failed to start ECR backing registry container" in message:
            raise RuntimeError(
                "Docker is reachable from the test runner, but Floci could not start its ECR "
                "sidecar through the mounted Docker socket. Check that the Docker engine permits "
                "root inside floci/floci:1.6.0 to use /var/run/docker.sock; older Docker Desktop "
                "versions may be incompatible."
            ) from exc
        raise
    repository_uri = repository["repositoryUri"]
    authorization = ecr.get_authorization_token()["authorizationData"][0]
    username, password = base64.b64decode(authorization["authorizationToken"]).decode().split(":", 1)
    docker_client.login(
        username=username,
        password=password,
        registry=authorization["proxyEndpoint"],
    )

    image_tag = f"{repository_uri}:{PROBE_TAG}"
    image_tags.append(image_tag)
    docker_client.images.build(
        path=str(PROBE_CONTEXT),
        tag=image_tag,
        platform="linux/amd64",
        rm=True,
    )
    for message in docker_client.api.push(image_tag, stream=True, decode=True):
        if error := message.get("error"):
            raise RuntimeError(f"Unable to push the probe image: {error}")

    image = ecr.describe_images(
        repositoryName=PROBE_REPOSITORY,
        imageIds=[{"imageTag": PROBE_TAG}],
    )["imageDetails"][0]
    return f"{repository_uri}@{image['imageDigest']}"


def run_tofu(endpoint: str, image_uri: str) -> None:
    environment = clean_environment(endpoint)
    template = (TERRAFORM_ROOT / "floci-tests" / "deployment.tftest.hcl").read_text()
    if template.count("__PROBE_IMAGE_URI__") != 1:
        raise RuntimeError("The Floci test must contain exactly one probe image marker.")
    rendered = template.replace("__PROBE_IMAGE_URI__", image_uri)
    with tempfile.TemporaryDirectory(prefix=".floci-tftest-", dir=TERRAFORM_ROOT) as test_dir:
        test_path = Path(test_dir)
        (test_path / "deployment.tftest.hcl").write_text(rendered)
        relative_test_dir = test_path.relative_to(TERRAFORM_ROOT)
        subprocess.run(
            [
                "tofu",
                f"-chdir={TERRAFORM_ROOT}",
                "init",
                "-backend=false",
                "-input=false",
                f"-test-directory={relative_test_dir}",
            ],
            check=True,
            env=environment,
        )
        subprocess.run(
            [
                "tofu",
                f"-chdir={TERRAFORM_ROOT}",
                "test",
                "-no-color",
                f"-test-directory={relative_test_dir}",
                f"-filter={relative_test_dir}/deployment.tftest.hcl",
                f"-var=aws_endpoint_url={endpoint}",
                f"-var=lambda_public_repo_url={image_uri}",
            ],
            check=True,
            env=environment,
        )


def main() -> int:
    try:
        docker_client = docker.from_env()
        docker_client.ping()
    except Exception as exc:
        raise RuntimeError(
            "The Floci E2E test requires a running Docker engine accessible to this process."
        ) from exc

    image_tags: list[str] = []
    floci = (
        FlociContainer(image=FLOCI_IMAGE)
        .with_kwargs(user="root")
        .with_env("AWS_ACCESS_KEY_ID", "test")
        .with_env("AWS_SECRET_ACCESS_KEY", "test")
        .with_env("FLOCI_SERVICES_ECR_KEEP_RUNNING_ON_SHUTDOWN", "false")
    )
    try:
        with floci:
            endpoint = floci.get_endpoint()
            try:
                image_uri = push_probe_image(docker_client, endpoint, image_tags)
                run_tofu(endpoint, image_uri)
            except Exception:
                stdout, stderr = floci.get_logs()
                logs = (stdout + stderr).decode(errors="replace")
                sys.stderr.write("\nFloci log tail:\n")
                sys.stderr.write(logs[-4000:])
                raise
    finally:
        for image_tag in image_tags:
            try:
                docker_client.images.remove(image_tag, force=True)
            except docker.errors.ImageNotFound:
                pass
        docker_client.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
