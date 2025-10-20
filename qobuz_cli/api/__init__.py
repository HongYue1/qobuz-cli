"""
Qobuz API Layer.

This package handles all communication with the official Qobuz API.
"""

from .auth import QobuzAuthenticator
from .client import QobuzAPIClient
from .rate_limiter import AdaptiveRateLimiter

__all__ = ["AdaptiveRateLimiter", "QobuzAPIClient", "QobuzAuthenticator"]
