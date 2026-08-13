FROM public.ecr.aws/lambda/python:3.13

COPY infra/daily-progress/lambda/docker/requirements.txt /tmp/requirements.txt
COPY packages/progress-collector /tmp/progress-collector
RUN pip install --no-cache-dir -r /tmp/requirements.txt /tmp/progress-collector \
    --target "${LAMBDA_TASK_ROOT}"

COPY infra/daily-progress/lambda/docker/daily_progress.py "${LAMBDA_TASK_ROOT}/daily_progress.py"
COPY infra/daily-progress/lambda/docker/lambda_handler.py "${LAMBDA_TASK_ROOT}/lambda_handler.py"

CMD ["lambda_handler.handler"]
