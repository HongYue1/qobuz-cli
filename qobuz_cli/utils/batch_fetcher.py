"""
Batch metadata fetching utilities for improved performance.
Fetches multiple albums/tracks in parallel with proper error handling.
"""

import asyncio
import logging
from typing import Any

log = logging.getLogger(__name__)


class BatchMetadataFetcher:
    """
    Handles batch fetching of metadata with concurrent requests and error recovery.
    """

    def __init__(self, api_client, max_concurrent: int = 10):
        """
        Args:
            api_client: The QobuzAPIClient instance.
            max_concurrent: Maximum number of concurrent metadata requests.
        """
        self.api_client = api_client
        self.semaphore = asyncio.Semaphore(max_concurrent)

    async def fetch_albums_batch(
        self, album_ids: list[str]
    ) -> dict[str, dict[str, Any] | None]:
        """
        Fetches multiple album metadata objects in parallel.

        Args:
            album_ids: List of album IDs to fetch.

        Returns:
            Dictionary mapping album_id -> metadata (or None if failed).
        """
        if not album_ids:
            return {}

        log.debug(f"Batch fetching metadata for {len(album_ids)} albums...")

        async def fetch_single(album_id: str) -> tuple[str, dict[str, Any] | None]:
            async with self.semaphore:
                try:
                    metadata = await self.api_client.fetch_album_metadata(album_id)
                    return album_id, metadata
                except Exception as e:
                    log.warning(f"Failed to fetch album {album_id}: {e}")
                    return album_id, None

        tasks = [fetch_single(aid) for aid in album_ids]
        results = await asyncio.gather(*tasks)

        return dict(results)

    async def fetch_tracks_batch(
        self, track_ids: list[str]
    ) -> dict[str, dict[str, Any] | None]:
        """
        Fetches multiple track metadata objects in parallel.

        Args:
            track_ids: List of track IDs to fetch.

        Returns:
            Dictionary mapping track_id -> metadata (or None if failed).
        """
        if not track_ids:
            return {}

        log.debug(f"Batch fetching metadata for {len(track_ids)} tracks...")

        async def fetch_single(track_id: str) -> tuple[str, dict[str, Any] | None]:
            async with self.semaphore:
                try:
                    metadata = await self.api_client.fetch_track_metadata(track_id)
                    return track_id, metadata
                except Exception as e:
                    log.warning(f"Failed to fetch track {track_id}: {e}")
                    return track_id, None

        tasks = [fetch_single(tid) for tid in track_ids]
        results = await asyncio.gather(*tasks)

        return dict(results)

    async def prefetch_album_tracks(
        self, album_ids: list[str]
    ) -> dict[str, dict[str, Any]]:
        """
        Pre-fetches all album metadata and their track lists.

        Args:
            album_ids: List of album IDs.

        Returns:
            Dictionary with album metadata and nested track information.
        """
        albums_metadata = await self.fetch_albums_batch(album_ids)

        result = {}
        for album_id, album_meta in albums_metadata.items():
            if album_meta:
                result[album_id] = {
                    "album": album_meta,
                    "tracks": album_meta.get("tracks", {}).get("items", []),
                    "track_count": len(album_meta.get("tracks", {}).get("items", [])),
                }

        return result
