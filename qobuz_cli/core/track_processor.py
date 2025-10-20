"""
Handles the processing of a single track, from download to tagging.
"""

import asyncio
import logging
import os
from collections import OrderedDict
from pathlib import Path
from typing import Any, Dict, Optional

from rich.markup import escape

from qobuz_cli.cli.progress_manager import ProgressManager
from qobuz_cli.exceptions import FileIntegrityError
from qobuz_cli.media import Downloader, FileIntegrityChecker, Tagger
from qobuz_cli.models.config import DownloadConfig, get_quality_info
from qobuz_cli.models.stats import DownloadStats
from qobuz_cli.storage.archive import TrackArchive
from qobuz_cli.utils.formatting import get_track_title
from qobuz_cli.utils.path import PathFormatter, create_dir

log = logging.getLogger(__name__)


class TrackProcessor:
    """
    Orchestrates the download, tagging, and archiving of a single track.
    """

    def __init__(
        self,
        config: DownloadConfig,
        archive: TrackArchive,
        stats: DownloadStats,
        downloader: Downloader,
        tagger: Tagger,
        progress_manager: ProgressManager,
    ):
        self.config = config
        self.archive = archive
        self.stats = stats
        self.downloader = downloader
        self.tagger = tagger
        self.progress_manager = progress_manager
        self.path_formatter = PathFormatter(config.output_template)
        self._asset_locks: OrderedDict[str, asyncio.Lock] = OrderedDict()
        self._max_locks = 1000  # Limit to 1000 concurrent album locks
        self._asset_lock_main = asyncio.Lock()

    async def _get_asset_lock(self, album_id: str) -> asyncio.Lock:
        """Gets or creates a lock for a given album ID to prevent race conditions on asset downloads."""
        async with self._asset_lock_main:
            if album_id in self._asset_locks:
                self._asset_locks.move_to_end(album_id)
                return self._asset_locks[album_id]

            lock = asyncio.Lock()
            self._asset_locks[album_id] = lock

            # Evict oldest if over limit
            if len(self._asset_locks) > self._max_locks:
                self._asset_locks.popitem(last=False)

            return lock

    async def process_track(
        self,
        track_meta: Dict[str, Any],
        album_meta: Dict[str, Any],
        track_url: Optional[str],
        output_dir_override: Optional[Path] = None,
        album_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Manages the complete lifecycle of downloading and saving a track.
        """
        track_id = str(track_meta["id"])
        quality_info = get_quality_info(self.config.quality)
        ext = quality_info["ext"]
        is_mp3 = ext == "mp3"

        # Get the full formatted path first
        full_formatted_path = self.path_formatter.format_path(
            track_meta, album_meta, ext
        )

        # Handle output directory override
        if output_dir_override:
            # CORRECTED LOGIC: Preserve the entire template-generated sub-path
            final_path = output_dir_override / full_formatted_path
        else:
            final_path = full_formatted_path

        final_dir = final_path.parent

        # Only create directory if NOT in dry run mode
        if not self.config.dry_run:
            create_dir(final_dir)

        # Create enhanced display title with album name
        album_title = album_meta.get("title", "Unknown Album")
        track_title = get_track_title(track_meta)
        track_display_title = f"{escape(album_title)} - {escape(track_title)}"

        if self.config.dry_run:
            self.stats.tracks_downloaded += 1
            # Use console.print to ensure it appears above the Live display
            self.progress_manager.console.print(
                f"  [cyan]→ (Dry Run)[/] Would save to [dim]{escape(str(final_path))}[/dim]"
            )
            # Increment skipped for progress tracking
            self.progress_manager.increment_skipped()
            return track_meta

        # Download cover art if needed (optimized double-checked locking)
        if not self.config.no_cover:
            album_id_str = str(album_meta.get("id"))
            if album_id_str:
                cover_path = final_dir / "cover.jpg"
                # First check (outside lock) for performance
                if not cover_path.exists():
                    cover_lock = await self._get_asset_lock(album_id_str)
                    async with cover_lock:
                        # Second check (inside lock) to prevent race condition
                        if not cover_path.exists():
                            if cover_url := album_meta.get("image", {}).get("large"):
                                log.debug(
                                    f"Downloading cover for album ID {album_id_str}"
                                )
                                await self.downloader.download_asset(
                                    cover_url,
                                    str(cover_path),
                                    self.config.og_cover,
                                    self.config.max_workers,
                                )

        if not track_url:
            self.stats.tracks_failed += 1
            log.error(f"  [red]✗ Failed:[/] {track_display_title} (No download URL)")
            return None

        if final_path.is_file():
            self.stats.tracks_skipped_exists += 1
            self.progress_manager.increment_skipped()
            log.info(
                f"  [yellow]○ Skipping:[/] [dim]{escape(final_path.name)}[/dim] (already exists)"
            )
            return None

        temp_path = final_path.with_suffix(f".{track_id}.tmp")

        # Estimate file size for progress bar
        size_estimate = track_meta.get("duration", 180) * (
            100 * 1024 if ext == "flac" else 40 * 1024
        )
        quality_str = quality_info["short"]

        # Estimate file size for display
        estimated_mb = size_estimate / (1024 * 1024)
        size_str = (
            f"{estimated_mb:.1f} MB"
            if estimated_mb >= 1
            else f"{estimated_mb * 1024:.0f} KB"
        )

        task_id = self.progress_manager.add_track_task(
            track_display_title,
            total_size=size_estimate,
            quality=quality_str,
            file_size_str=size_str,
        )

        try:
            await self.downloader.download_file(
                url=track_url,
                destination_path=str(temp_path),
                total_size_estimate=size_estimate,
                stats=self.stats,
                progress_manager=self.progress_manager,
                task_id=task_id,
                max_workers=self.config.max_workers,
            )

            self.tagger.tag_file(
                str(temp_path), str(final_path), track_meta, album_meta, is_mp3
            )

            if not (
                FileIntegrityChecker.check_mp3(str(final_path))
                if is_mp3
                else FileIntegrityChecker.check_flac(str(final_path))
            ):
                raise FileIntegrityError("Downloaded file failed integrity check.")

            self.stats.tracks_downloaded += 1
            if final_path.exists():
                downloaded_size = final_path.stat().st_size
                self.stats.total_size_downloaded += downloaded_size

            self.progress_manager.remove_task(task_id, success=True)
            if album_id:
                self.progress_manager.increment_album_progress(album_id)
            return track_meta

        except Exception as e:
            self.stats.tracks_failed += 1
            self.progress_manager.remove_task(task_id, success=False)
            log.error(
                f"  [red]✗ Failed:[/] {track_display_title} ({e})",
                exc_info=log.getEffectiveLevel() == logging.DEBUG,
            )
            return None
        finally:
            if temp_path.exists():
                try:
                    os.remove(temp_path)
                except OSError:
                    pass
