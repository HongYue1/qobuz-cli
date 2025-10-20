"""
Handles the low-level downloading of files over HTTP with adaptive chunk sizing
and compression support for optimal performance.
"""

import asyncio
import logging
import os

import aiofiles
import aiohttp
from rich.progress import TaskID

from qobuz_cli.cli.progress_manager import ProgressManager
from qobuz_cli.models.stats import DownloadStats

log = logging.getLogger(__name__)

_connection_pool: aiohttp.ClientSession | None = None
_pool_lock = asyncio.Lock()


async def get_connection_pool(max_workers: int = 8) -> aiohttp.ClientSession:
    """
    Gets or creates a shared aiohttp ClientSession for downloads.

    This function ensures that only one connection pool is created for the
    lifetime of the application run.

    Args:
        max_workers: Maximum concurrent connections (should match config.max_workers).
    """
    global _connection_pool
    async with _pool_lock:
        if _connection_pool and not _connection_pool.closed:
            return _connection_pool

        connector = aiohttp.TCPConnector(
            limit=max_workers * 2,  # Total connections
            limit_per_host=max_workers,  # Per-host (Qobuz CDN)
            ttl_dns_cache=600,  # 10 minutes
            keepalive_timeout=30,
            enable_cleanup_closed=True,
            force_close=False,
        )
        timeout = aiohttp.ClientTimeout(total=None, sock_connect=15, sock_read=90)
        _connection_pool = aiohttp.ClientSession(
            connector=connector,
            timeout=timeout,
            headers={
                "Accept-Encoding": "gzip, deflate, br",
            },
        )
        log.debug(f"Created download pool with limit_per_host={max_workers}")

    return _connection_pool


async def close_connection_pool() -> None:
    """Closes the shared global connection pool."""
    global _connection_pool
    async with _pool_lock:
        if _connection_pool and not _connection_pool.closed:
            await _connection_pool.close()
            _connection_pool = None
            log.debug("Shared downloader connection pool closed.")


class Downloader:
    """A low-level file downloader with retry logic and adaptive chunk sizing."""

    MIN_CHUNK_SIZE = 131072  # 128 KB
    MAX_CHUNK_SIZE = 1048576  # 1 MB
    _shared_chunk_size = MIN_CHUNK_SIZE
    _chunk_lock = asyncio.Lock()

    def __init__(self, max_attempts: int = 3, base_delay: float = 1.5):
        self.max_attempts = max_attempts
        self.base_delay = base_delay

    @classmethod
    async def _adapt_chunk_size_shared(cls, current_speed_bps: float) -> int:
        """Adapts the shared chunk size based on current network speed."""
        async with cls._chunk_lock:
            if current_speed_bps > 10 * 1024 * 1024:  # > 10 MB/s
                cls._shared_chunk_size = cls.MAX_CHUNK_SIZE
            elif current_speed_bps > 5 * 1024 * 1024:  # > 5 MB/s
                cls._shared_chunk_size = 524288  # 512 KB
            elif current_speed_bps > 1 * 1024 * 1024:  # > 1 MB/s
                cls._shared_chunk_size = 262144  # 256 KB
            else:
                cls._shared_chunk_size = cls.MIN_CHUNK_SIZE
            return cls._shared_chunk_size

    async def download_file(
        self,
        url: str,
        destination_path: str,
        total_size_estimate: int,
        stats: DownloadStats | None = None,
        progress_manager: ProgressManager | None = None,
        task_id: TaskID | None = None,
        max_workers: int = 8,
    ) -> None:
        """
        Downloads a file from a URL with adaptive chunking, updating a Rich Progress
        instance.
        """
        last_exception = None
        for attempt in range(1, self.max_attempts + 1):
            try:
                session = await get_connection_pool(max_workers)
                async with session.get(url, allow_redirects=True) as response:
                    response.raise_for_status()

                    effective_total_size = int(
                        response.headers.get("Content-Length", total_size_estimate)
                    )
                    if progress_manager and task_id is not None:
                        progress_manager.update_task_total(
                            task_id, total=effective_total_size
                        )

                    async with aiofiles.open(destination_path, "wb") as f:
                        bytes_downloaded = 0
                        last_speed_check = asyncio.get_event_loop().time()
                        chunk_size = self._shared_chunk_size

                        async for chunk in response.content.iter_chunked(chunk_size):
                            await f.write(chunk)
                            bytes_downloaded += len(chunk)

                            if stats:
                                await stats.update_speed_stats(
                                    stats.total_size_downloaded + bytes_downloaded,
                                    progress_manager,
                                )
                                now = asyncio.get_event_loop().time()
                                if now - last_speed_check > 2.0:
                                    chunk_size = await self._adapt_chunk_size_shared(
                                        stats.current_speed_bps
                                    )
                                    last_speed_check = now

                            if progress_manager and task_id is not None:
                                progress_manager.update_task_progress(
                                    task_id, completed=bytes_downloaded
                                )
                return
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                last_exception = e
                log.debug(
                    f"Download attempt {attempt}/{self.max_attempts} for "
                    f"'{os.path.basename(destination_path)}' failed: {e}. Retrying..."
                )
                if attempt < self.max_attempts:
                    await asyncio.sleep(self.base_delay * (2 ** (attempt - 1)))

        if last_exception:
            raise last_exception

    async def download_asset(
        self,
        url: str,
        destination_path: str,
        use_original_quality: bool,
        max_workers: int = 8,
    ) -> None:
        """
        Downloads an asset (like a cover image or booklet) if it doesn't already exist.
        """
        path_exists = await asyncio.to_thread(os.path.isfile, destination_path)
        if path_exists:
            return

        if use_original_quality:
            url = url.replace("_600.", "_org.")

        try:
            await self.download_file(
                url, destination_path, total_size_estimate=0, max_workers=max_workers
            )
        except Exception as e:
            log.debug(
                f"Failed to download asset '{os.path.basename(destination_path)}': {e}"
            )
