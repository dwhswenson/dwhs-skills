"""Normalized, read-only collection of personal progress data."""

from .auth_config import AuthConfigError, AuthConfigStore, default_auth_config_path
from .config import CalendarConfig, GitHubConfig, LinearConfig
from .core import CollectionFailed, Collector, collect_all, default_collectors
from .models import Activity, CollectionDocument, SourceResult, TimeRange

__all__ = [
    "Activity",
    "AuthConfigError",
    "AuthConfigStore",
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
    "default_auth_config_path",
]
