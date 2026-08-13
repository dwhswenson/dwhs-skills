"""AWS Lambda entry point for the daily progress collector."""

from daily_progress import DailyProgressTask

handler = DailyProgressTask().lambda_handler
