"""
Web Scraping Layer.

This package contains modules for fetching and parsing data from the
Qobuz web player, primarily to extract API secrets.
"""

from .bundle_fetcher import BundleFetcher

__all__ = ["BundleFetcher"]
