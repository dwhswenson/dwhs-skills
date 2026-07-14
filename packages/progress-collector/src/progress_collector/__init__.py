"""Normalized, read-only collection of personal progress data."""

from .config import CalendarConfig, GitHubConfig, LinearConfig
from .core import CollectionFailed, Collector, collect_all, default_collectors
from .models import Activity, CollectionDocument, SourceResult, TimeRange

__all__ = [
    "Activity",
    "CalendarConfig",
    "CollectionDocument",
    "CollectionFailed",
    "Collector",
    "GitHubConfig",
    "LinearConfig",
    "SourceResult",
    "TimeRange",
    "collect_all",
    "default_collectors",
]
