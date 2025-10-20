"""
A simple, file-based JSON cache with a time-to-live (TTL) for storing API responses.
Enhanced with statistics tracking for cache hits and misses.
"""

import asyncio
import hashlib
import json
import logging
import time
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


class CacheManager:
    """
    Manages a JSON-based file cache with TTL, periodic cleanup, and statistics tracking.
    """

    MAX_CACHE_VALUE_KB = 500

    def __init__(
        self,
        cache_dir_path: Path,
        max_age_days: int = 1,
        stats_callback: Callable[[bool], None] | None = None,
    ):
        """
        Initializes the cache manager.

        Args:
            cache_dir_path: The directory where cache files will be stored.
            max_age_days: The maximum age of a cache entry in days before it expires.
            stats_callback: Optional callback to report cache hits (True) or misses
            (False).
        """
        self.cache_dir = cache_dir_path / "cache"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.max_age_seconds = max_age_days * 86400
        self._stats_callback = stats_callback
        self._cleanup_task: asyncio.Task | None = None

    async def start_background_cleanup(self):
        """Starts the periodic background cleanup task."""
        if self._cleanup_task is None or self._cleanup_task.done():
            self._cleanup_task = asyncio.create_task(self._cleanup_loop())
            log.debug("Started cache background cleanup task.")

    async def _cleanup_loop(self):
        """Runs the cleanup logic periodically in the background."""
        while True:
            try:
                await asyncio.to_thread(self._cleanup_expired_entries)
                await asyncio.sleep(3600)
            except asyncio.CancelledError:
                log.debug("Cache cleanup task cancelled.")
                break
            except Exception as e:
                log.warning(f"Error in cache cleanup loop: {e}")
                await asyncio.sleep(3600)

    async def stop_background_cleanup(self):
        """Stops the background cleanup task gracefully."""
        if self._cleanup_task and not self._cleanup_task.done():
            self._cleanup_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._cleanup_task
            log.debug("Stopped cache background cleanup task.")

    def _get_cache_path(self, key: str) -> Path:
        """Generates a safe filename for a given cache key."""
        hashed_key = hashlib.md5(key.encode("utf-8")).hexdigest()  # noqa: S324
        return self.cache_dir / f"{hashed_key}.json"

    def _cleanup_expired_entries(self) -> None:
        """Scans the cache directory and removes expired files."""
        now = time.time()
        cleaned_count = 0
        for cache_file in self.cache_dir.glob("*.json"):
            try:
                if now - cache_file.stat().st_mtime > self.max_age_seconds:
                    cache_file.unlink()
                    cleaned_count += 1
            except OSError as e:
                log.warning(
                    f"Failed to remove expired cache file {cache_file.name}: {e}"
                )
        if cleaned_count > 0:
            log.debug(f"Cache cleanup: removed {cleaned_count} expired entries.")

    def get(self, key: str) -> Any | None:
        """
        Retrieves a value from the cache. Returns None if the key is not found or
        expired.
        """
        cache_path = self._get_cache_path(key)

        if not cache_path.is_file():
            if self._stats_callback:
                self._stats_callback(False)
            return None

        try:
            if time.time() - cache_path.stat().st_mtime > self.max_age_seconds:
                cache_path.unlink()
                if self._stats_callback:
                    self._stats_callback(False)
                return None

            with open(cache_path, encoding="utf-8") as f:
                data = json.load(f)
                if self._stats_callback:
                    self._stats_callback(True)
                return data.get("value")
        except (json.JSONDecodeError, OSError) as e:
            log.debug(f"Cache read failed for key '{key}': {e}")
            if self._stats_callback:
                self._stats_callback(False)
            return None

    def set(self, key: str, value: Any) -> bool:
        """
        Saves a value to the cache, with a size limit check.
        """
        cache_path = self._get_cache_path(key)
        try:
            payload = {
                "key": key,
                "timestamp": time.time(),
                "value": value,
            }
            serialized_payload = json.dumps(payload)
            size_kb = len(serialized_payload) / 1024

            if size_kb > self.MAX_CACHE_VALUE_KB:
                log.debug(
                    f"Cache value for key '{key}' is too large ({size_kb:.1f} KB), "
                    "skipping."
                )
                return False

            with open(cache_path, "w", encoding="utf-8") as f:
                f.write(serialized_payload)
            return True
        except (TypeError, OSError) as e:
            log.warning(f"Cache write failed for key '{key}': {e}")
            return False

    def clear(self) -> bool:
        """Removes all items from the cache."""
        log.info("Clearing all cache entries...")
        try:
            for cache_file in self.cache_dir.glob("*.json"):
                cache_file.unlink()
            return True
        except OSError as e:
            log.error(f"Failed to clear cache: {e}")
            return False
