"""Run the Docker-backed daily-progress infrastructure test against Floci."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

import boto3
import docker
from botocore.config import Config
from botocore.exceptions import ClientError
from floci import FlociContainer


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
TERRAFORM_ROOT = REPOSITORY_ROOT / "infra" / "daily-progress"
PROBE_CONTEXT = TERRAFORM_ROOT / "floci-tests" / "probe"
FLOCI_IMAGE = "floci/floci:2.1.0"
PROBE_BASE_IMAGE = "public.ecr.aws/lambda/python:3.13"
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


def push_probe_image(
    docker_client, endpoint: str, image_tags: list[str], registry_container_name: str
) -> str:
    ecr = aws_client("ecr", endpoint)
    try:
        repository = ecr.create_repository(repositoryName=PROBE_REPOSITORY)[
            "repository"
        ]
    except ClientError as exc:
        message = exc.response.get("Error", {}).get("Message", "")
        if "Failed to start ECR backing registry container" in message:
            raise RuntimeError(
                "Docker is reachable from the test runner, but Floci could not start its ECR "
                "sidecar through the mounted Docker socket. Check that the Docker engine permits "
                "floci/floci:2.1.0 to use /var/run/docker.sock and that Docker Desktop Enhanced "
                "Container Isolation allows this image."
            ) from exc
        raise
    registry = docker_client.containers.get(registry_container_name)
    registry.reload()
    registry_port = registry.attrs["NetworkSettings"]["Ports"]["5000/tcp"][0][
        "HostPort"
    ]
    repository_path = repository["repositoryUri"].split("/", 1)[1]
    repository_uri = f"localhost:{registry_port}/{repository_path}"

    image_tag = f"{repository_uri}:{PROBE_TAG}"
    image_tags.append(image_tag)
    docker_client.images.pull(PROBE_BASE_IMAGE, platform="linux/amd64", auth_config={})
    docker_client.images.build(
        path=str(PROBE_CONTEXT),
        tag=image_tag,
        platform="linux/amd64",
        rm=True,
    )
    image_digest = None
    for message in docker_client.api.push(image_tag, stream=True, decode=True):
        if error := message.get("error"):
            raise RuntimeError(f"Unable to push the probe image: {error}")
        if digest := message.get("aux", {}).get("Digest"):
            image_digest = digest
        elif "digest: sha256:" in (status := message.get("status", "")):
            image_digest = f"sha256:{status.split('digest: sha256:', 1)[1].split()[0]}"

    if image_digest is None:
        raise RuntimeError(
            "Docker pushed the probe image without returning its digest."
        )
    return f"{repository_uri}@{image_digest}"


def run_tofu(endpoint: str, image_uri: str) -> None:
    environment = clean_environment(endpoint)
    errored_state = TERRAFORM_ROOT / "errored_test.tfstate"
    if errored_state.exists():
        raise RuntimeError(
            f"Refusing to overwrite an existing OpenTofu failure state: {errored_state}"
        )
    template = (TERRAFORM_ROOT / "floci-tests" / "deployment.tftest.hcl").read_text()
    if template.count("__PROBE_IMAGE_URI__") != 1:
        raise RuntimeError(
            "The Floci test must contain exactly one probe image marker."
        )
    rendered = template.replace("__PROBE_IMAGE_URI__", image_uri)
    try:
        with tempfile.TemporaryDirectory(
            prefix=".floci-tftest-", dir=TERRAFORM_ROOT
        ) as test_dir:
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
                ],
                check=True,
                env=environment,
            )
    finally:
        errored_state.unlink(missing_ok=True)


def main() -> int:
    previous_docker_config = os.environ.get("DOCKER_CONFIG")
    docker_config = tempfile.TemporaryDirectory(prefix="daily-progress-docker-config-")
    os.environ["DOCKER_CONFIG"] = docker_config.name
    docker_client = None
    try:
        docker_client = docker.from_env()
        docker_client.ping()
    except Exception as exc:
        if docker_client is not None:
            docker_client.close()
        docker_config.cleanup()
        if previous_docker_config is None:
            os.environ.pop("DOCKER_CONFIG", None)
        else:
            os.environ["DOCKER_CONFIG"] = previous_docker_config
        raise RuntimeError(
            "The Floci E2E test requires a running Docker engine accessible to this process."
        ) from exc

    image_tags: list[str] = []
    registry_container_name = f"daily-progress-e2e-ecr-{uuid.uuid4().hex[:12]}"
    registry_volume_name = "floci-ecr-registry-data"
    try:
        docker_client.volumes.get(registry_volume_name)
        remove_registry_volume = False
    except docker.errors.NotFound:
        remove_registry_volume = True
    floci = (
        FlociContainer(image=FLOCI_IMAGE)
        .with_env("AWS_ACCESS_KEY_ID", "test")
        .with_env("AWS_SECRET_ACCESS_KEY", "test")
        .with_env("FLOCI_RUN_AS_ROOT", "true")
        .with_env("FLOCI_SERVICES_ECR_KEEP_RUNNING_ON_SHUTDOWN", "false")
        .with_env("FLOCI_SERVICES_ECR_REGISTRY_CONTAINER_NAME", registry_container_name)
        .with_env("FLOCI_SERVICES_ECR_URI_STYLE", "path")
    )
    try:
        with floci:
            endpoint = floci.get_endpoint()
            try:
                image_uri = push_probe_image(
                    docker_client, endpoint, image_tags, registry_container_name
                )
                run_tofu(endpoint, image_uri)
            except Exception:
                stdout, stderr = floci.get_logs()
                logs = (stdout + stderr).decode(errors="replace")
                sys.stderr.write("\nFloci log tail:\n")
                sys.stderr.write(logs[-16000:])
                raise
    finally:
        try:
            for image_tag in image_tags:
                try:
                    docker_client.images.remove(image_tag, force=True)
                except docker.errors.ImageNotFound:
                    pass
            try:
                docker_client.containers.get(registry_container_name).remove(force=True)
            except docker.errors.NotFound:
                pass
            if remove_registry_volume:
                try:
                    docker_client.volumes.get(registry_volume_name).remove(force=True)
                except docker.errors.NotFound:
                    pass
        finally:
            docker_client.close()
            docker_config.cleanup()
            if previous_docker_config is None:
                os.environ.pop("DOCKER_CONFIG", None)
            else:
                os.environ["DOCKER_CONFIG"] = previous_docker_config
    return 0


if __name__ == "__main__":
    sys.exit(main())
