"""
Manages the SQLite database that archives downloaded track IDs to prevent redownloading.
"""

import asyncio
import logging
import os
import sqlite3
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


class TrackArchive:
    """
    A thread-safe SQLite archive for storing downloaded track metadata
    with connection pooling and optimized batch operations.
    """

    def __init__(self, config_dir_path: Path, pool_size: int = 5):
        self.db_path = config_dir_path / "download_archive.sqlite"
        self._pool_size = pool_size
        self._connection_semaphore = asyncio.Semaphore(pool_size)
        self._initialize_db()
        self._migrate_from_txt_if_needed(config_dir_path)

    def _get_connection(self) -> sqlite3.Connection:
        """Gets a new database connection with optimized PRAGMA settings."""
        try:
            conn = sqlite3.connect(self.db_path, timeout=30, check_same_thread=False)
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA synchronous=NORMAL;")
            conn.execute("PRAGMA temp_store=MEMORY;")
            conn.execute("PRAGMA cache_size=-64000;")
            return conn
        except sqlite3.Error as e:
            log.error(f"Failed to connect to archive database: {e}")
            raise

    def _initialize_db(self) -> None:
        """
        Creates the database and table with optimized settings and indexes if they
        don't exist.
        """
        try:
            with self._get_connection() as conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS downloaded_tracks (
                        track_id TEXT PRIMARY KEY NOT NULL,
                        artist TEXT,
                        album TEXT,
                        title TEXT,
                        downloaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    );
                    """
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_artist ON"
                    " downloaded_tracks(artist);"
                )
                conn.commit()
        except sqlite3.Error as e:
            log.error(f"Failed to initialize archive database at '{self.db_path}': {e}")

    def _migrate_from_txt_if_needed(self, config_dir_path: Path) -> None:
        """
        One-time migration from the old text-based archive to the new SQLite database.
        """
        txt_archive_path = config_dir_path / "download_archive.txt"
        if not txt_archive_path.is_file():
            return

        log.info(
            "[yellow]Migrating from legacy text archive to SQLite database...[/yellow]"
        )
        try:
            with open(txt_archive_path, encoding="utf-8") as f:
                track_ids = [line.strip() for line in f if line.strip()]

            if track_ids:
                records = [(tid,) for tid in track_ids]
                with self._get_connection() as conn:
                    conn.executemany(
                        "INSERT OR IGNORE INTO downloaded_tracks (track_id) VALUES (?)",
                        records,
                    )
                    conn.commit()
                log.info(
                    f"[green]✓ Migrated {len(track_ids)} entries from the "
                    "text archive.[/green]"
                )

            backup_path = txt_archive_path.with_suffix(".txt.migrated")
            os.rename(txt_archive_path, backup_path)
            log.info(
                f"[dim]The old text archive has been renamed to '{backup_path.name}'"
                "[/dim]"
            )
        except (OSError, sqlite3.Error) as e:
            log.error(f"[red]Migration from text archive failed: {e}[/red]")

    async def _run_in_executor(self, func, *args):
        """Runs a synchronous database function within the connection pool semaphore."""
        async with self._connection_semaphore:
            return await asyncio.to_thread(func, *args)

    def _check_batch_sync(self, track_ids: list[str]) -> dict[str, bool]:
        """Synchronous implementation for checking a batch of track IDs in chunks."""
        if not track_ids:
            return {}

        BATCH_SIZE = (
            999  # SQLite's default limit on variables in a query prior to 3.32.0
        )
        results = {}
        try:
            with self._get_connection() as conn:
                for i in range(0, len(track_ids), BATCH_SIZE):
                    chunk = track_ids[i : i + BATCH_SIZE]
                    placeholders = ",".join("?" * len(chunk))
                    query = (
                        "SELECT track_id FROM downloaded_tracks WHERE track_id IN"  # noqa: S608
                        f" ({placeholders})"
                    )
                    cursor = conn.execute(query, chunk)
                    existing_ids = {row[0] for row in cursor.fetchall()}
                    chunk_results = dict.fromkeys(chunk, False)
                    chunk_results.update(dict.fromkeys(existing_ids, True))
                    results.update(chunk_results)
            return results
        except sqlite3.Error as e:
            log.error(f"Batch archive check failed: {e}")
            return dict.fromkeys(track_ids, False)

    async def check_if_tracks_exist(self, track_ids: list[str]) -> dict[str, bool]:
        """Checks if a batch of track IDs exist in the archive."""
        return await self._run_in_executor(self._check_batch_sync, track_ids)

    def _add_batch_sync(self, track_metas: list[dict[str, Any]]) -> bool:
        """Synchronous implementation for adding a batch of tracks in chunks."""
        records = [
            (
                str(meta["id"]),
                meta.get("performer", {}).get("name"),
                meta.get("album", {}).get("title"),
                meta.get("title"),
            )
            for meta in track_metas
            if meta.get("id")
        ]
        if not records:
            return True

        BATCH_SIZE = 500
        try:
            with self._get_connection() as conn:
                for i in range(0, len(records), BATCH_SIZE):
                    chunk = records[i : i + BATCH_SIZE]
                    conn.executemany(
                        "INSERT OR IGNORE INTO downloaded_tracks "
                        "(track_id, artist, album, title) VALUES (?, ?, ?, ?)",
                        chunk,
                    )
                conn.commit()
            return True
        except sqlite3.Error as e:
            log.error(
                f"Batch insert into archive failed for {len(records)} tracks: {e}"
            )
            return False

    async def add_tracks(self, track_metas: list[dict[str, Any]]) -> bool:
        """Adds a batch of tracks to the archive."""
        return await self._run_in_executor(self._add_batch_sync, track_metas)

    def _get_stats_sync(self) -> dict[str, Any] | None:
        """Synchronous implementation for getting archive statistics."""
        try:
            with self._get_connection() as conn:
                cur = conn.cursor()
                cur.execute("SELECT COUNT(*) FROM downloaded_tracks")
                total_tracks = cur.fetchone()[0]
                cur.execute(
                    """
                    SELECT artist, COUNT(*) as count
                    FROM downloaded_tracks
                    WHERE artist IS NOT NULL AND artist != ''
                    GROUP BY artist
                    ORDER BY count DESC
                    LIMIT 10
                    """
                )
                top_artists = cur.fetchall()
                return {"total_tracks": total_tracks, "top_artists": top_artists}
        except sqlite3.Error as e:
            log.error(f"Failed to get archive stats: {e}")
            return None

    async def get_stats(self) -> dict[str, Any] | None:
        """Retrieves statistics from the download archive."""
        return await self._run_in_executor(self._get_stats_sync)

    def _vacuum_sync(self) -> bool:
        """Synchronous implementation for optimizing the database."""
        try:
            with self._get_connection() as conn:
                conn.execute("VACUUM;")
                conn.execute("ANALYZE;")
                conn.commit()
            log.info("Archive database optimized successfully.")
            return True
        except sqlite3.Error as e:
            log.error(f"Database vacuum failed: {e}")
            return False

    async def vacuum(self) -> bool:
        """Optimizes the database file by rebuilding it."""
        return await self._run_in_executor(self._vacuum_sync)
