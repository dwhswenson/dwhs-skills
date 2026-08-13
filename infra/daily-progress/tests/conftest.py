"""Test setup for importing the Lambda code without its runtime-only lambdacron package."""

from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType


class StubCronLambdaTask:
    def __init__(self, **kwargs):
        self.cron_kwargs = kwargs

    def lambda_handler(self, event, context):
        return self._perform_task(event, context)


lambdacron = ModuleType("lambdacron")
lambda_task = ModuleType("lambdacron.lambda_task")
lambda_task.CronLambdaTask = StubCronLambdaTask
sys.modules.setdefault("lambdacron", lambdacron)
sys.modules.setdefault("lambdacron.lambda_task", lambda_task)

DOCKER_DIR = Path(__file__).resolve().parents[1] / "lambda" / "docker"
sys.path.insert(0, str(DOCKER_DIR))
