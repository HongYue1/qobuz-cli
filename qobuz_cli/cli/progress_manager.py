"""
Manages a Rich Live display with enhanced visualization for concurrent downloads.
Shows overall progress, active downloads, MULTIPLE CONCURRENT ALBUMS, and real-time
statistics.
"""

import asyncio
import logging
from datetime import datetime
from typing import Any

from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    DownloadColumn,
    Progress,
    SpinnerColumn,
    TaskID,
    TextColumn,
    TimeRemainingColumn,
    TransferSpeedColumn,
)
from rich.table import Table
from rich.text import Text

log = logging.getLogger("qobuz_cli")


class ProgressManager:
    """
    An enhanced manager with real-time statistics, concurrent download visualization,
    and MULTIPLE ALBUM context tracking (up to 5 concurrent albums).
    """

    def __init__(self, console: Console, dry_run: bool = False):
        self.console = console
        self.dry_run = dry_run

        self.progress = Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}", justify="left"),
            BarColumn(bar_width=20),
            "[progress.percentage]{task.percentage:>3.0f}%",
            "•",
            DownloadColumn(),
            "•",
            TransferSpeedColumn(),
            "•",
            TimeRemainingColumn(),
            console=console,
            transient=False,
        )

        self.overall_progress = Progress(
            TextColumn("[bold blue]{task.description}"),
            BarColumn(bar_width=40),
            "[progress.percentage]{task.percentage:>3.0f}%",
            console=console,
        )

        self._live: Live | None = None
        self._layout: Layout | None = None

        self._stats = {
            "total_tracks": 0,
            "completed": 0,
            "failed": 0,
            "skipped": 0,
            "active_downloads": 0,
            "peak_concurrent": 0,
            "total_size": 0,
            "downloaded_size": 0,
            "start_time": None,
            "current_speed": 0.0,
            "avg_speed": 0.0,
            "peak_speed": 0.0,
            "cache_hits": 0,
            "cache_misses": 0,
        }

        self._current_albums: dict[str, dict[str, Any]] = {}
        self._overall_task_id: TaskID | None = None
        self._active_tasks: dict[TaskID, dict] = {}

    def log_message(self, message: str, level: str = "info"):
        """Unified logging respecting dry_run mode."""
        if self.dry_run:
            style_map = {
                "info": "cyan",
                "warning": "yellow",
                "error": "red",
                "success": "green",
            }
            style = style_map.get(level, "")
            self.console.print(f"[{style}]{message}[/{style}]" if style else message)
        else:
            getattr(log, level, log.info)(message)

    def set_current_album(
        self, artist: str, title: str, total_tracks: int, album_id: str | None = None
    ):
        album_key = album_id or f"{artist}_{title}"
        self._current_albums[album_key] = {
            "artist": artist,
            "title": title,
            "completed": 0,
            "total": total_tracks,
        }
        if len(self._current_albums) > 5:
            self._current_albums.pop(next(iter(self._current_albums)))

    def increment_album_progress(self, album_id: str | None = None, count: int = 1):
        album_key = album_id
        if album_key and album_key in self._current_albums:
            self._current_albums[album_key]["completed"] += count
        elif self._current_albums and not album_key:
            last_key = next(reversed(self._current_albums))
            self._current_albums[last_key]["completed"] += count

    def clear_current_album(self, album_id: str | None = None):
        if album_id and album_id in self._current_albums:
            del self._current_albums[album_id]
        elif self._current_albums:
            self._current_albums.popitem()

    def update_speed_stats(
        self, current_speed: float, avg_speed: float, peak_speed: float
    ):
        self._stats["current_speed"] = current_speed
        self._stats["avg_speed"] = avg_speed
        self._stats["peak_speed"] = peak_speed

    def record_cache_hit(self):
        self._stats["cache_hits"] += 1

    def record_cache_miss(self):
        self._stats["cache_misses"] += 1

    def _create_layout(self) -> Layout:
        layout = Layout()
        layout.split_column(
            Layout(name="header", size=3),
            Layout(name="stats", size=9),
            Layout(name="album_context", size=8),
            Layout(name="progress", ratio=1),
        )
        return layout

    def _generate_header(self) -> Panel:
        if self._stats["start_time"]:
            elapsed = (datetime.now() - self._stats["start_time"]).total_seconds()
            elapsed_str = f"{int(elapsed // 3600):02d}:"
            f"{int((elapsed % 3600) // 60):02d}:{int(elapsed % 60):02d}"
        else:
            elapsed_str = "00:00:00"
        header_text = Text()
        header_text.append("🎵 Qobuz Downloader ", style="bold cyan")
        header_text.append("│ ", style="dim")
        header_text.append(f"Session: {elapsed_str}", style="yellow")
        if self._stats["current_speed"] > 0:
            speed_mb = self._stats["current_speed"] / (1024 * 1024)
            header_text.append(" │ ", style="dim")
            header_text.append(f"⚡ {speed_mb:.1f} MB/s", style="magenta")
        return Panel(header_text, border_style="cyan")

    def _generate_stats_panel(self) -> Panel:
        stats_table = Table.grid(padding=(0, 2))
        stats_table.add_column(style="bold cyan", justify="right")
        stats_table.add_column(style="white")
        stats_table.add_column(style="bold cyan", justify="right")
        stats_table.add_column(style="white")
        stats_table.add_row(
            "Downloaded:",
            f"[green]{self._stats['completed']}[/green]",
            "Failed:",
            f"[red]{self._stats['failed']}[/red]",
        )
        skipped_val = (
            self._stats["total_tracks"]
            - self._stats["completed"]
            - self._stats["failed"]
            - self._stats["skipped"]
        )
        stats_table.add_row(
            "Skipped:",
            f"[yellow]{self._stats['skipped']}[/yellow]",
            "Remaining:",
            f"[cyan]{skipped_val}[/cyan]",
        )
        stats_table.add_row(
            "Active:",
            f"[cyan]{self._stats['active_downloads']}[/cyan]",
            "Peak:",
            f"[magenta]{self._stats['peak_concurrent']}[/magenta]",
        )
        if self._stats["avg_speed"] > 0:
            avg_speed_mb = self._stats["avg_speed"] / (1024 * 1024)
            peak_speed_mb = self._stats["peak_speed"] / (1024 * 1024)
            stats_table.add_row(
                "Avg Speed:",
                f"[blue]{avg_speed_mb:.1f} MB/s[/blue]",
                "Peak Speed:",
                f"[magenta]{peak_speed_mb:.1f} MB/s[/magenta]",
            )
        total_cache = self._stats["cache_hits"] + self._stats["cache_misses"]
        if total_cache > 0:
            cache_rate = (self._stats["cache_hits"] / total_cache) * 100
            stats_table.add_row(
                "Cache Hits:",
                f"[green]{self._stats['cache_hits']}[/green]",
                "Hit Rate:",
                f"[green]{cache_rate:.0f}%[/green]",
            )
        combined = Table.grid()
        combined.add_row(stats_table)
        combined.add_row("")
        if self._overall_task_id is not None:
            combined.add_row(self.overall_progress)
        return Panel(
            combined, title="[bold]📊 Session Statistics[/bold]", border_style="blue"
        )

    def _generate_album_context_panel(self) -> Panel:
        if not self._current_albums:
            return Panel(
                Text(
                    "No albums currently processing...",
                    style="dim italic",
                    justify="center",
                ),
                title="[bold]🎵 Current Albums[/bold]",
                border_style="green",
            )
        term_width = self.console.width
        chars_per_album = 28
        max_albums = max(1, min(5, term_width // chars_per_album))
        num_albums = len(self._current_albums)
        albums_to_show = list(self._current_albums.values())[:max_albums]
        album_grid = Table.grid(padding=(0, 2))
        for _ in range(len(albums_to_show)):
            album_grid.add_column(style="white", vertical="top", min_width=20)
        album_cards = []
        for album_info in albums_to_show:
            card = Table.grid(padding=(0, 0))
            card.add_column(style="bold", justify="left", width=23)
            artist = (
                album_info["artist"][:20] + "…"
                if len(album_info["artist"]) > 23
                else album_info["artist"]
            )
            title = (
                album_info["title"][:20] + "…"
                if len(album_info["title"]) > 23
                else album_info["title"]
            )
            progress_pct = (
                (album_info["completed"] / album_info["total"] * 100)
                if album_info["total"] > 0
                else 0
            )
            bar_width = 18
            filled = int(bar_width * progress_pct / 100)
            bar = "█" * filled + "░" * (bar_width - filled)
            bar_color = (
                "green"
                if progress_pct == 100
                else "cyan"
                if progress_pct > 50
                else "yellow"
            )
            card.add_row(f"[cyan]{artist}[/cyan]")
            card.add_row(f"[yellow]{title}[/yellow]")
            card.add_row(f"[{bar_color}]{bar}[/{bar_color}]")
            card.add_row(f"[dim]{album_info['completed']}/{album_info['total']}[/dim]")
            album_cards.append(card)
        album_grid.add_row(*album_cards)
        title_text = f"[bold]🎵 Albums ({num_albums})[/bold]"
        if num_albums > max_albums:
            title_text = f"[bold]🎵 Albums ({max_albums}/{num_albums} shown)[/bold]"
        return Panel(album_grid, title=title_text, border_style="green")

    def _generate_progress_panel(self) -> Panel:
        if not self._active_tasks:
            return Panel(
                Text(
                    "Waiting for downloads to start...",
                    style="dim italic",
                    justify="center",
                ),
                title="[bold]📥 Active Downloads[/bold]",
                border_style="green",
            )
        return Panel(
            self.progress,
            title=f"[bold]📥 Active Downloads ({len(self._active_tasks)})[/bold]",
            border_style="green",
        )

    def _update_display(self):
        """
        Updates all panels in the layout, letting the Live object handle refresh rate.
        """
        if self.dry_run or not self._layout:
            return

        self._layout["header"].update(self._generate_header())
        self._layout["stats"].update(self._generate_stats_panel())
        self._layout["album_context"].update(self._generate_album_context_panel())
        self._layout["progress"].update(self._generate_progress_panel())

    def initialize_session(self, total_tracks: int | None):
        self._stats["total_tracks"] = total_tracks or 0
        self._stats["start_time"] = datetime.now()
        if not self.dry_run:
            self._overall_task_id = self.overall_progress.add_task(
                "Overall Progress", total=total_tracks, start=True
            )

    def add_to_total(self, count: int):
        if self.dry_run or self._overall_task_id is None:
            return
        self._stats["total_tracks"] += count
        self.overall_progress.update(
            self._overall_task_id, total=self._stats["total_tracks"]
        )

    def add_track_task(
        self,
        description: str,
        total_size: int,
        quality: str = "",
        file_size_str: str = "",
    ) -> TaskID:
        if self.dry_run:
            return None
        if len(description) > 55:
            parts = description.split(" - ", 1)
            if len(parts) == 2:
                album, track = parts
                if len(track) > 30:
                    track = "…" + track[-27:]
                if len(album) > 22:
                    album = album[:20] + "…"
                description = f"{album} - {track}"
            else:
                description = description[:52] + "..."
        quality_colors = {
            "MP3 320": "yellow",
            "16/44.1": "green",
            "24/96": "cyan",
            "24/192": "magenta",
        }
        quality_color = quality_colors.get(quality, "white")
        quality_display = (
            f"[{quality_color}]{quality}[/{quality_color}]" if quality else ""
        )
        metadata = []
        if file_size_str:
            metadata.append(f"[dim]{file_size_str}[/dim]")
        if quality_display:
            metadata.append(quality_display)
        display_desc = (
            f"{description} [{' | '.join(metadata)}]" if metadata else description
        )
        task_id = self.progress.add_task(display_desc, total=total_size, start=True)
        self._active_tasks[task_id] = {
            "description": description,
            "size": total_size,
            "quality": quality,
        }
        self._stats["active_downloads"] = len(self._active_tasks)
        self._stats["peak_concurrent"] = max(
            self._stats["peak_concurrent"], self._stats["active_downloads"]
        )
        self._update_display()
        return task_id

    def update_task_progress(self, task_id: TaskID, completed: int):
        if task_id is not None and not self.dry_run:
            self.progress.update(task_id, completed=completed)
            self._update_display()

    def update_task_total(self, task_id: TaskID, total: int):
        if task_id is not None and not self.dry_run:
            self.progress.update(task_id, total=total)

    def remove_task(self, task_id: TaskID, success: bool = True):
        if task_id is None or self.dry_run:
            return
        try:
            self.progress.remove_task(task_id)
            if task_id in self._active_tasks:
                del self._active_tasks[task_id]
            self._stats["active_downloads"] = len(self._active_tasks)
            if success:
                self._stats["completed"] += 1
            else:
                self._stats["failed"] += 1
            if self._overall_task_id is not None:
                self.overall_progress.update(
                    self._overall_task_id,
                    completed=(
                        self._stats["completed"]
                        + self._stats["failed"]
                        + self._stats["skipped"]
                    ),
                )
            self._update_display()
        except KeyError:
            pass

    def increment_skipped(self, count: int = 1):
        self._stats["skipped"] += count
        if self._overall_task_id is not None and not self.dry_run:
            self.overall_progress.update(
                self._overall_task_id,
                completed=(
                    self._stats["completed"]
                    + self._stats["failed"]
                    + self._stats["skipped"]
                ),
            )
        self._update_display()

    def get_statistics(self) -> dict:
        return self._stats.copy()

    async def __aenter__(self):
        if self.dry_run:
            return self
        self._layout = self._create_layout()
        self._update_display()
        self._live = Live(
            self._layout,
            console=self.console,
            refresh_per_second=12,
            vertical_overflow="visible",
        )
        self._live.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._live and not self.dry_run:
            await asyncio.sleep(0.2)
            self._live.stop()
