"""
The main orchestrator for handling URLs, fetching metadata, and managing the download queue.
"""

import asyncio
import json
import logging
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import aiohttp
from bs4 import BeautifulSoup
from rich.markup import escape

from qobuz_cli.api.client import QobuzAPIClient
from qobuz_cli.cli.progress_manager import ProgressManager
from qobuz_cli.exceptions import NotStreamableError, QobuzCliError
from qobuz_cli.media import Downloader, Tagger
from qobuz_cli.models.config import DownloadConfig
from qobuz_cli.models.stats import DownloadStats
from qobuz_cli.storage.archive import TrackArchive
from qobuz_cli.storage.cache import CacheManager
from qobuz_cli.utils.batch_fetcher import BatchMetadataFetcher
from qobuz_cli.utils.discography import smart_discography_filter
from qobuz_cli.utils.formatting import extract_artist_name
from qobuz_cli.utils.path import create_dir, parse_qobuz_url
from qobuz_cli.utils.playlist import generate_m3u

from .track_processor import TrackProcessor

log = logging.getLogger(__name__)


class DownloadManager:
    """Orchestrates the entire download process."""

    def __init__(
        self,
        config: DownloadConfig,
        api_client: QobuzAPIClient,
        archive: TrackArchive,
        progress_manager: ProgressManager,
    ):
        self.config = config
        self.api_client = api_client
        self.archive = archive
        self.stats = DownloadStats(dry_run=config.dry_run)
        self.start_time = time.monotonic()
        self.cache = CacheManager(Path(config.config_path))
        self.track_processor = TrackProcessor(
            config,
            archive,
            self.stats,
            Downloader(),
            Tagger(config.embed_art),
            progress_manager,
        )
        self.batch_fetcher = BatchMetadataFetcher(api_client, max_concurrent=10)

        def cache_stats_callback(is_hit: bool):
            if is_hit:
                self.track_processor.progress_manager.record_cache_hit()
            else:
                self.track_processor.progress_manager.record_cache_miss()

        self.cache._stats_callback = cache_stats_callback
        self.semaphore = asyncio.Semaphore(config.max_workers)
        self._processed_album_ids = set()
        self._processed_playlist_ids = set()
        self._processed_ids_lock = asyncio.Lock()  # Lock for processed sets

    def save_session_stats(self):
        """Saves the current session's stats to a history file."""
        stats_file = Path(self.config.config_path) / "session_history.jsonl"
        try:
            with open(stats_file, "a", encoding="utf-8") as f:
                elapsed_time = time.monotonic() - self.start_time
                session_data = {
                    "timestamp": int(time.time()),
                    "tracks_downloaded": self.stats.tracks_downloaded,
                    "tracks_skipped_archive": self.stats.tracks_skipped_archive,
                    "tracks_skipped_exists": self.stats.tracks_skipped_exists,
                    "tracks_skipped_quality": self.stats.tracks_skipped_quality,
                    "tracks_failed": self.stats.tracks_failed,
                    "total_size_downloaded": self.stats.total_size_downloaded,
                    "duration_seconds": round(elapsed_time, 2),
                    "albums_processed_count": len(self.stats.albums_processed),
                }
                json.dump(session_data, f)
                f.write("\n")
        except IOError as e:
            log.warning(f"[yellow]Could not save session stats:[/] {e}")

    async def execute_downloads(self):
        """Processes all URLs from the config and executes downloads."""
        await self.cache.start_background_cleanup()
        try:
            if not self.config.source_urls:
                log.info("No source URLs provided. Nothing to do.")
                return

            expanded_urls = []
            for source in self.config.source_urls:
                if Path(source).is_file():
                    log.info(f"Reading URLs from file: [dim]{source}[/dim]")
                    try:
                        with open(source, "r", encoding="utf-8") as f:
                            expanded_urls.extend(
                                line.strip()
                                for line in f
                                if line.strip() and not line.startswith("#")
                            )
                    except (IOError, UnicodeDecodeError) as e:
                        log.error(f"[red]Could not read file {source}: {e}[/red]")
                else:
                    expanded_urls.append(source)

            unique_urls = list(dict.fromkeys(expanded_urls))
            if len(unique_urls) < len(expanded_urls):
                log.info(
                    f"Removed {len(expanded_urls) - len(unique_urls)} duplicate URLs."
                )

            if not unique_urls:
                log.warning(
                    "[yellow]No unique or valid URLs to process. Exiting.[/yellow]"
                )
                return

            self.track_processor.progress_manager.initialize_session(total_tracks=None)

            tasks = [self._process_url(url) for url in unique_urls]
            await asyncio.gather(*tasks)
        finally:
            await self.cache.stop_background_cleanup()

    async def _process_url(self, url: str):
        """Routes a single URL to the appropriate handler."""
        if "last.fm" in url:
            await self._process_lastfm_playlist(url)
            return

        url_info = parse_qobuz_url(url)
        if not url_info:
            log.error(f"[red]Invalid or unsupported URL: {escape(url)}[/red]")
            return

        url_type, item_id = url_info

        handlers = {
            "album": self._process_album,
            "track": self._process_track,
            "artist": self._process_artist,
            "playlist": self._process_playlist,
            "label": self._process_label,
        }

        handler = handlers.get(url_type)
        if handler:
            try:
                await handler(item_id)
            except NotStreamableError as e:
                log.warning(f"[yellow]⚠ {e}[/yellow]")
            except Exception as e:
                log.error(f"[red]✗ Error processing URL: {e}[/red]")
        else:
            log.warning(
                f"Handler for URL type '{escape(url_type)}' is not implemented."
            )

    async def _process_album(
        self, album_id: str, output_dir_override: Optional[Path] = None
    ):
        """Downloads a full album with batch URL fetching."""
        async with self._processed_ids_lock:
            if album_id in self._processed_album_ids:
                self.track_processor.progress_manager.log_message(
                    f"Album ID '{escape(album_id)}' has already been processed. Skipping."
                )
                return
            self._processed_album_ids.add(album_id)

        self.stats.albums_processed.add(f"album_{album_id}")

        cache_key = f"album_meta_{album_id}"
        if self.cache and (cached_meta := self.cache.get(cache_key)):
            album_meta = cached_meta
            log.debug(f"Loaded album metadata for '{album_id}' from cache.")
        else:
            album_meta = await self.api_client.fetch_album_metadata(album_id)
            if self.cache:
                self.cache.set(cache_key, album_meta)

        tracks_count = len(album_meta.get("tracks", {}).get("items", []))
        self.track_processor.progress_manager.add_to_total(tracks_count)

        if not album_meta.get("streamable", False):
            self.track_processor.progress_manager.log_message(
                f"[yellow]⚠ Album '{escape(album_meta.get('title', album_id))}' is not available for streaming. Skipping.[/yellow]",
                level="warning",
            )
            self.stats.albums_skipped = getattr(self.stats, "albums_skipped", 0) + 1
            return

        artist = album_meta.get("artist", {}).get("name", "Unknown Artist")
        title = album_meta.get("title", "Unknown Album")
        self.track_processor.progress_manager.set_current_album(
            artist, title, tracks_count, album_id=album_id
        )

        if self.config.albums_only and (
            album_meta.get("release_type") != "album"
            or album_meta.get("artist", {}).get("name") == "Various Artists"
        ):
            self.track_processor.progress_manager.log_message(
                f"Skipping non-album release: {album_meta.get('title', 'N/A')}"
            )
            # Account for skipped tracks
            self.track_processor.progress_manager.increment_skipped(tracks_count)
            self.track_processor.progress_manager.increment_album_progress(
                album_id, tracks_count
            )
            return

        year = str(album_meta.get("release_date_original", "0"))[:4]
        self.track_processor.progress_manager.log_message(
            f"\n[bold cyan]▶ Album:[/] {escape(artist)} - {escape(title)} ({year})"
        )

        tracks = album_meta.get("tracks", {}).get("items", [])
        track_ids_to_check = [str(t["id"]) for t in tracks]

        archive_status = {}
        if self.config.download_archive and not self.config.dry_run:
            archive_status = await self.archive.check_if_tracks_exist(
                track_ids_to_check
            )

        processable_tracks = [t for t in tracks if not archive_status.get(str(t["id"]))]
        skipped_count = len(tracks) - len(processable_tracks)

        if skipped_count > 0:
            self.stats.tracks_skipped_archive += skipped_count
            self.track_processor.progress_manager.increment_skipped(skipped_count)
            self.track_processor.progress_manager.increment_album_progress(
                album_id, skipped_count
            )
            self.track_processor.progress_manager.log_message(
                f"  [yellow]○ Skipped {skipped_count} tracks (already in archive).[/yellow]",
                level="info",
            )

        if not self.config.dry_run and processable_tracks:
            track_ids = [str(t["id"]) for t in processable_tracks]
            url_tasks = [
                self.api_client.fetch_track_url(tid, self.config.quality)
                for tid in track_ids
            ]
            url_results = await asyncio.gather(*url_tasks, return_exceptions=True)
            tasks = []
            for track, url_data in zip(processable_tracks, url_results):
                if isinstance(url_data, Exception):
                    self.stats.tracks_failed += 1
                    log.error(f"Failed to get URL for track {track['id']}: {url_data}")
                    continue
                tasks.append(
                    self._get_and_process_track(
                        track,
                        album_meta,
                        output_dir_override,
                        album_id,
                        track_url_data=url_data,
                    )
                )
            await asyncio.gather(*tasks)
        else:
            tasks = [
                self._get_and_process_track(
                    track, album_meta, output_dir_override, album_id
                )
                for track in processable_tracks
            ]
            await asyncio.gather(*tasks)

        self.track_processor.progress_manager.clear_current_album(album_id=album_id)

    async def _process_track(self, track_id: str):
        """Downloads a single track."""
        self.track_processor.progress_manager.add_to_total(1)
        cache_key = f"track_meta_{track_id}"
        if self.cache and (cached_meta := self.cache.get(cache_key)):
            track_meta = cached_meta
            log.debug(f"Loaded track metadata for '{track_id}' from cache.")
        else:
            track_meta = await self.api_client.fetch_track_metadata(track_id)
            if self.cache:
                self.cache.set(cache_key, track_meta)

        archive_status = {}
        if self.config.download_archive:
            archive_status = await self.archive.check_if_tracks_exist([str(track_id)])

        if archive_status.get(str(track_id)):
            self.stats.tracks_skipped_archive += 1
            self.track_processor.progress_manager.increment_skipped()
            self.track_processor.progress_manager.log_message(
                f"[yellow]Skipping track '{escape(track_meta['title'])}' (already in archive).[/yellow]",
                level="warning",
            )
            return

        album_meta = track_meta.get("album", {})
        artist = escape(album_meta.get("artist", {}).get("name", "Unknown Artist"))
        title = escape(album_meta.get("title", "Unknown Album"))
        self.track_processor.progress_manager.log_message(
            f"\n[bold cyan]▶ From Album:[/] {artist} - {title}"
        )
        await self._get_and_process_track(track_meta, album_meta)

    async def _process_artist(self, artist_id: str):
        """Downloads the discography of an artist, streaming albums to conserve memory."""
        artist_discography_gen = self.api_client.fetch_artist_discography(artist_id)
        try:
            first_page = await artist_discography_gen.__anext__()
        except StopAsyncIteration:
            self.track_processor.progress_manager.log_message(
                f"Artist ID '{escape(artist_id)}' has no albums.", level="warning"
            )
            return

        artist_name = extract_artist_name(first_page, fallback_id=artist_id)
        sanitized_artist_name = re.sub(r'[<>:"/\\|?*]', "_", artist_name).strip()
        artist_dir = Path(sanitized_artist_name)

        if not self.config.dry_run:
            create_dir(artist_dir)

        self.track_processor.progress_manager.log_message(
            f"\n[bold magenta]🎤 Artist Discography:[/] {escape(artist_name)}"
        )

        if self.config.smart_discography:
            all_albums = first_page.get("albums", {}).get("items", [])
            async for page in artist_discography_gen:
                all_albums.extend(page.get("albums", {}).get("items", []))

            self.track_processor.progress_manager.log_message(
                f"  [dim]Applying smart discography filter to {len(all_albums)} albums...[/dim]"
            )
            filtered_albums = await asyncio.to_thread(
                smart_discography_filter, all_albums
            )
            self.track_processor.progress_manager.log_message(
                f"  [dim]{len(filtered_albums)} albums remaining after filtering.[/dim]"
            )
            for album in filtered_albums:
                await self._process_album(album["id"], output_dir_override=artist_dir)
        else:
            processed_count = 0
            for album in first_page.get("albums", {}).get("items", []):
                await self._process_album(album["id"], output_dir_override=artist_dir)
                processed_count += 1

            async for page in artist_discography_gen:
                for album in page.get("albums", {}).get("items", []):
                    await self._process_album(
                        album["id"], output_dir_override=artist_dir
                    )
                    processed_count += 1
            self.track_processor.progress_manager.log_message(
                f"  [dim]Processed {processed_count} total albums.[/dim]"
            )

    async def _process_playlist(
        self,
        playlist_id: str,
        lastfm_title: Optional[str] = None,
        track_ids_override: Optional[List[str]] = None,
    ):
        """Downloads a playlist."""
        async with self._processed_ids_lock:
            if playlist_id in self._processed_playlist_ids and not lastfm_title:
                return
            self._processed_playlist_ids.add(playlist_id)

        playlist_name, playlist_dir, all_tracks = None, None, []

        if lastfm_title:
            playlist_name = lastfm_title
            playlist_dir = Path(re.sub(r'[<>:"/\\|?*]', "_", playlist_name).strip())
            if not self.config.dry_run:
                create_dir(playlist_dir)
            track_meta_tasks = [
                self.api_client.fetch_track_metadata(tid) for tid in track_ids_override
            ]
            all_tracks = await asyncio.gather(*track_meta_tasks)
        else:
            first_page = await self.api_client.api_call(
                "playlist/get", playlist_id=playlist_id
            )
            playlist_name = first_page.get("name", f"playlist_{playlist_id}")
            playlist_dir = Path(re.sub(r'[<>:"/\\|?*]', "_", playlist_name).strip())
            if not self.config.dry_run:
                create_dir(playlist_dir)
            async for page in self.api_client.fetch_playlist_tracks(playlist_id):
                all_tracks.extend(page.get("tracks", {}).get("items", []))

        self.track_processor.progress_manager.add_to_total(len(all_tracks))
        self.track_processor.progress_manager.log_message(
            f"\n[bold green]🎵 Playlist:[/] {escape(playlist_name)}"
        )
        self.stats.albums_processed.add(f"playlist_{playlist_id}")

        for track in all_tracks:
            album_meta = track.get("album", {})
            await self._get_and_process_track(
                track, album_meta, output_dir_override=playlist_dir
            )

        if not self.config.no_m3u and not self.config.dry_run:
            generate_m3u(playlist_dir)

    async def _process_label(self, label_id: str):
        """Downloads all albums from a label."""
        label_discography_gen = self.api_client.fetch_label_discography(label_id)
        try:
            first_page = await label_discography_gen.__anext__()
        except StopAsyncIteration:
            self.track_processor.progress_manager.log_message(
                f"Label ID '{escape(label_id)}' has no albums.", level="warning"
            )
            return

        label_name = first_page.get("label", {}).get("name", f"Label ID {label_id}")
        sanitized_label_name = re.sub(r'[<>:"/\\|?*]', "_", label_name).strip()
        label_dir = Path(sanitized_label_name)

        if not self.config.dry_run:
            create_dir(label_dir)

        self.track_processor.progress_manager.log_message(
            f"\n[bold yellow]🏢 Label:[/] {escape(label_name)}"
        )

        all_albums = first_page.get("albums", {}).get("items", [])
        async for page in label_discography_gen:
            all_albums.extend(page.get("albums", {}).get("items", []))

        for album in all_albums:
            await self._process_album(album["id"], output_dir_override=label_dir)

    async def _get_and_process_track(
        self,
        track_meta: Dict[str, Any],
        album_meta: Dict[str, Any],
        output_dir_override: Optional[Path] = None,
        album_id: Optional[str] = None,
        track_url_data: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Fetches a track's download URL and passes it to the TrackProcessor.
        """
        if self.config.dry_run:
            await self.track_processor.process_track(
                track_meta,
                album_meta,
                track_url=None,
                output_dir_override=output_dir_override,
                album_id=album_id,
            )
            return track_meta

        async with self.semaphore:
            try:
                url_data = track_url_data or await self.api_client.fetch_track_url(
                    track_meta["id"], self.config.quality
                )

                restrictions = url_data.get("restrictions", [])
                quality_restricted = any(
                    r.get("code") == "FormatRestrictedByFormatAvailability"
                    for r in restrictions
                )

                if quality_restricted and self.config.no_fallback:
                    log.warning(
                        f"  [yellow]Skipping track '{escape(track_meta['title'])}': requested quality not available.[/yellow]"
                    )
                    self.stats.tracks_skipped_quality += 1
                    self.track_processor.progress_manager.increment_skipped()
                    self.track_processor.progress_manager.increment_album_progress(
                        album_id
                    )
                    return None

                if processed_meta := await self.track_processor.process_track(
                    track_meta,
                    album_meta,
                    url_data.get("url"),
                    output_dir_override,
                    album_id,
                ):
                    if self.config.download_archive:
                        await self.archive.add_tracks([processed_meta])
                    return processed_meta
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                self.stats.tracks_failed += 1
                log.error(
                    f"[red]  ✗ Network error for track '{escape(track_meta.get('title', 'Unknown'))}': {e}[/red]"
                )
            except QobuzCliError as e:
                self.stats.tracks_failed += 1
                log.error(
                    f"[red]  ✗ API error for track '{escape(track_meta.get('title', 'Unknown'))}': {e}[/red]"
                )
            except Exception as e:
                self.stats.tracks_failed += 1
                log.error(
                    f"[red]  ✗ An unexpected error occurred for track '{escape(track_meta.get('title', 'Unknown'))}': {e}[/red]",
                    exc_info=log.getEffectiveLevel() == logging.DEBUG,
                )
            # A failure here should still count toward album progress
            self.track_processor.progress_manager.increment_album_progress(album_id)
            return None

    async def _search_for_track_id(self, query: str) -> Optional[str]:
        """Searches Qobuz for a track and returns its ID."""
        cache_key = f"search_{query}"
        if self.cache and (cached_id := self.cache.get(cache_key)):
            return cached_id

        try:
            results = await self.api_client.search_tracks(query=query, limit=1)
            if items := results.get("tracks", {}).get("items", []):
                track_id = str(items[0]["id"])
                if self.cache:
                    self.cache.set(cache_key, track_id)
                return track_id
        except Exception as e:
            log.debug(f"Track search for '{query}' failed: {e}")
        return None

    async def _process_lastfm_playlist(self, url: str):
        """Fetches a Last.fm playlist, searches for tracks on Qobuz, and downloads them."""
        log.info(f"Processing Last.fm playlist: [dim]{url}[/dim]")
        try:
            timeout = aiohttp.ClientTimeout(total=30)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url) as response:
                    response.raise_for_status()
                    html = await response.text()
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            log.error(f"[red]Failed to fetch Last.fm playlist: {e}[/red]")
            return

        soup = BeautifulSoup(html, "html.parser")
        artists = [el.text.strip() for el in soup.select("td.chartlist-artist > a")]
        titles = [el.text.strip() for el in soup.select("td.chartlist-name > a")]
        pl_title_element = soup.select_one("h1.header-title")
        pl_title = (
            pl_title_element.text.strip() if pl_title_element else "Last.fm Playlist"
        )

        if not artists or not titles:
            log.warning("[yellow]No tracks found on Last.fm page.[/yellow]")
            return

        search_queries = [f"{artist} {title}" for artist, title in zip(artists, titles)]
        log.info(f"Found {len(search_queries)} tracks. Searching for them on Qobuz...")

        search_tasks = [self._search_for_track_id(q) for q in search_queries]
        track_ids = [tid for tid in await asyncio.gather(*search_tasks) if tid]

        if not track_ids:
            log.warning("[yellow]Could not find any matching tracks on Qobuz.[/yellow]")
            return

        found_ratio = (len(track_ids) / len(search_queries)) * 100
        log.info(
            f"Found {len(track_ids)}/{len(search_queries)} matching tracks on Qobuz ({found_ratio:.0f}%)."
        )

        await self._process_playlist(
            playlist_id="lastfm_playlist",
            lastfm_title=pl_title,
            track_ids_override=track_ids,
        )
