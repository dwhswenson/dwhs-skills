---
name: pr-review-queue
description: Retrieve and present the authenticated user's pending GitHub pull request review queue from the configured Lambda endpoint. Use when the user asks which PRs are awaiting their review, requests their pending GitHub reviews, or wants to distinguish fresh review requests from re-reviews.
---

# PR Review Queue

Fetch the review queue through the bundled client instead of querying GitHub directly.

## Retrieve the queue

1. Require `GITHUB_PR_LAMBDA_URL` and `GITHUB_PR_LAMBDA_TOKEN` in the environment.
2. Run:

   ```bash
   python3 scripts/fetch_review_queue.py
   ```

3. Return the generated Markdown to the user without adding reviews from other sources.

The command groups re-reviews before fresh requests and orders each group by the oldest update first. A re-review with no new head commit is identified explicitly as a renewed request at the same commit.

## Machine-readable output

Use `--json` only when the user requests raw data or another tool needs the Lambda response:

```bash
python3 scripts/fetch_review_queue.py --json
```

## Local development

To run the same review-queue snapshot logic locally without Lambda, Secrets Manager, or S3:

```bash
export GITHUB_PR_GITHUB_TOKEN=...
python3 scripts/run_local_review_queue.py
python3 scripts/run_local_review_queue.py --json
python3 scripts/run_local_review_queue.py --output /tmp/review-queue.json
```

The local runner queries GitHub directly with `GITHUB_PR_GITHUB_TOKEN`, prints Markdown by default, and writes the canonical JSON snapshot when `--output` is provided.

## Errors

- Report missing environment variables as configuration errors.
- Report endpoint authentication and upstream failures concisely.
- Never print or repeat the bearer token.
- Do not claim that the queue or S3 dashboard snapshot was refreshed when the Lambda returns an error.
