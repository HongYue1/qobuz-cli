"""
Pydantic model for tracking download session statistics.
"""

import asyncio
import time
from dataclasses import dataclass, field


@dataclass
class DownloadStats:
    """Tracks statistics for a download session, including real-time speed."""

    tracks_downloaded: int = 0
    tracks_skipped_archive: int = 0
    tracks_skipped_exists: int = 0
    tracks_skipped_quality: int = 0
    tracks_failed: int = 0
    total_size_downloaded: int = 0
    dry_run: bool = False
    albums_processed: set[str] = field(default_factory=set)
    albums_skipped: int = 0

    # Real-time speed calculation fields
    current_speed_bps: float = 0.0
    peak_speed_bps: float = 0.0
    _speed_samples: list[float] = field(default_factory=list, repr=False)
    _last_progress_time: float = field(default=0.0, repr=False)
    _last_progress_bytes: int = field(default=0, repr=False)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)

    def __post_init__(self):
        self._last_progress_time = time.monotonic()

    async def update_speed_stats(
        self, total_bytes_so_far: int, progress_manager=None
    ) -> None:
        """
        Updates the download speed based on progress. This method is now async-safe.

        Args:
            total_bytes_so_far: The cumulative total of bytes downloaded in the session.
        """
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_progress_time

            # Update speed roughly twice per second
            if elapsed > 0.5:
                bytes_diff = total_bytes_so_far - self._last_progress_bytes
                if bytes_diff > 0 and elapsed > 0:
                    speed = bytes_diff / elapsed
                    self._speed_samples.append(speed)
                    # Keep a sliding window of the last 10 speed samples
                    if len(self._speed_samples) > 10:
                        self._speed_samples.pop(0)

                    if self._speed_samples:
                        self.current_speed_bps = sum(self._speed_samples) / len(
                            self._speed_samples
                        )
                        self.peak_speed_bps = max(
                            self.peak_speed_bps, self.current_speed_bps
                        )

                        # Update progress manager if available
                        if progress_manager:
                            avg_speed = sum(self._speed_samples) / len(
                                self._speed_samples
                            )
                            progress_manager.update_speed_stats(
                                self.current_speed_bps, avg_speed, self.peak_speed_bps
                            )

                self._last_progress_time = now
                self._last_progress_bytes = total_bytes_so_far
