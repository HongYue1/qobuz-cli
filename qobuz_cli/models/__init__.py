"""
Data Models Layer.

This package contains Pydantic models that define the core data structures
used throughout the application, such as configuration and statistics.
"""

from .config import DownloadConfig
from .stats import DownloadStats

__all__ = ["DownloadConfig", "DownloadStats"]
