"""End-to-end smoke test for qobuz-cli.

Exercises the live Qobuz API, metadata scraping, tag/path formatting, and a real
single-track download (audio + embedded art + cover.jpg + booklet.pdf + lyrics +
ReplayGain) against a known album, then validates every produced artifact.

Requires a working configuration (run ``qobuz-cli init <TOKEN>`` first).

Usage:
    uv run python scripts/smoke_test.py
    uv run python scripts/smoke_test.py <ALBUM_URL> --quality 2 --keep
"""

from __future__ import annotations

import argparse
import asyncio
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

from mutagen import File as MutagenFile
from rich.console import Console
from rich.table import Table

from qobuz_cli.api.client import QobuzAPIClient
from qobuz_cli.cli.app import CONFIG_DIR, CONFIG_FILE
from qobuz_cli.cli.progress_manager import ProgressManager
from qobuz_cli.core.track_processor import TrackProcessor, extract_booklet_url
from qobuz_cli.media.downloader import Downloader, close_connection_pool
from qobuz_cli.media.tagger import Tagger
from qobuz_cli.models.config import (
    DownloadConfig,
    get_quality_info,
    resolve_download_format,
)
from qobuz_cli.models.stats import DownloadStats
from qobuz_cli.storage.archive import TrackArchive
from qobuz_cli.storage.config_manager import ConfigManager
from qobuz_cli.utils.formatting import get_track_title
from qobuz_cli.utils.path import parse_qobuz_url

DEFAULT_URL = "https://play.qobuz.com/album/0088807231568"
console = Console()


class Recorder:
    """Collects and prints PASS/FAIL/SKIP results for each smoke-test step."""

    def __init__(self) -> None:
        self.results: list[tuple[str, bool, bool, str]] = []

    def record(
        self, name: str, ok: bool, detail: str = "", *, hard: bool = True
    ) -> bool:
        self.results.append((name, ok, hard, detail))
        if ok:
            mark = "[green]\u2713 PASS[/green]"
        elif hard:
            mark = "[red]\u2717 FAIL[/red]"
        else:
            mark = "[yellow]\u25cb SKIP[/yellow]"
        line = f"  {mark}  {name}"
        if detail:
            line += f"  [dim]{detail}[/dim]"
        console.print(line)
        return ok

    def hard_failures(self) -> int:
        return sum(1 for _, ok, hard, _ in self.results if hard and not ok)


async def run_live(
    config: DownloadConfig, url: str, out_dir: Path, rec: Recorder
) -> dict[str, Any] | None:
    """Run every live network check and a real download.

    Returns a context dict for the synchronous artifact validation, or None if a
    hard failure aborted the run early.
    """
    client = QobuzAPIClient(config.app_id, config.secrets, config.max_workers)
    try:
        # 1. Authentication (user token).
        user_info = await client.authenticator.authenticate_with_token(config.token)
        email = user_info.get("email", "unknown") if isinstance(user_info, dict) else ""
        rec.record("Token authentication", bool(user_info), f"user: {email}")

        # 2. App-secret discovery (needed to sign file-URL requests).
        await client.authenticator.configure_authentication()
        rec.record(
            "App-secret discovery",
            bool(client.app_secret),
            "secret resolved" if client.app_secret else "no working secret",
        )

        # 3. URL parsing.
        parsed = parse_qobuz_url(url)
        rec.record(
            "URL parsing",
            parsed is not None and parsed[0] == "album",
            str(parsed) if parsed else "unparseable",
        )
        if not parsed:
            return None
        _, album_id = parsed

        # 4. Album metadata fetch + schema validation.
        album_meta = await client.fetch_album_metadata(album_id)
        items = album_meta.get("tracks", {}).get("items", [])
        required = ["id", "title", "artist", "tracks_count", "image", "media_count"]
        missing = [k for k in required if k not in album_meta]
        rec.record(
            "Album metadata fetch",
            not missing and bool(items),
            f"{album_meta.get('title')} \u2014 {len(items)} tracks"
            if not missing
            else f"missing keys: {missing}",
        )
        if not items:
            return None

        # 5. Metadata scrape -> tag mapping (validates the scraped format).
        track_meta = items[0]
        tagger = Tagger(embed_art=config.embed_art, write_replaygain=config.replaygain)
        tags = tagger._get_common_tags(track_meta, album_meta)
        needed = ["title", "album", "artist", "albumartist", "tracknumber"]
        empty = [k for k in needed if not tags.get(k)]
        rec.record(
            "Metadata -> tag mapping",
            not empty,
            f"title='{tags.get('title')}', artist={tags.get('artist')}"
            if not empty
            else f"empty tags: {empty}",
        )

        # 6. Booklet detection.
        booklet_url = extract_booklet_url(album_meta)
        rec.record(
            "Booklet detection",
            bool(booklet_url),
            "booklet URL found" if booklet_url else "no booklet in metadata",
        )

        # 7. Track file-URL fetch (signed request).
        track_id = str(track_meta["id"])
        url_data = await client.fetch_track_url(track_id, config.quality)
        actual_id, downgraded = resolve_download_format(config.quality, url_data)
        quality_short = get_quality_info(actual_id)["short"]
        rec.record(
            "Track file-URL fetch",
            bool(url_data.get("url")),
            f"format={quality_short}" + (" (downgraded)" if downgraded else ""),
        )

        # 8. Live single-track download (audio + cover + booklet + lyrics + RG).
        stats = DownloadStats(dry_run=False)
        downloader = Downloader()
        archive = TrackArchive(CONFIG_DIR)
        async with ProgressManager(console=console, dry_run=False) as pm:
            pm.initialize_session(total_tracks=1)
            pm.add_to_total(1)
            processor = TrackProcessor(config, archive, stats, downloader, tagger, pm)
            result = await processor.process_track(
                track_meta,
                album_meta,
                url_data.get("url"),
                output_dir_override=out_dir,
                album_id=album_id,
                actual_format_id=actual_id,
            )
    finally:
        await close_connection_pool()
        await client.close()

    return {
        "result": result,
        "album_meta": album_meta,
        "track_meta": track_meta,
        "actual_id": actual_id,
        "booklet_url": booklet_url,
        "embed_art": config.embed_art,
    }


def validate_output(out_dir: Path, ctx: dict[str, Any], rec: Recorder) -> None:
    """Validate the artifacts produced by the live download (synchronous I/O)."""
    result = ctx["result"]
    album_meta = ctx["album_meta"]
    track_meta = ctx["track_meta"]
    actual_id = ctx["actual_id"]
    booklet_url = ctx["booklet_url"]

    # 9. Audio file produced + sanity.
    audio_files = sorted(out_dir.rglob("*.flac")) + sorted(out_dir.rglob("*.mp3"))
    produced = audio_files[0] if audio_files else None
    rec.record(
        "Live track download",
        result is not None and produced is not None,
        f"saved {produced.name}" if produced else "no audio file produced",
    )
    if produced is None:
        return

    size = produced.stat().st_size
    rec.record("Audio file non-empty", size > 0, f"{size / 1024 / 1024:.1f} MB")
    expected_ext = get_quality_info(actual_id)["ext"]
    rec.record(
        "Audio extension matches quality",
        produced.suffix.lstrip(".") == expected_ext,
        f"{produced.suffix} vs .{expected_ext}",
    )

    # 10. Embedded tags round-trip.
    easy = MutagenFile(str(produced), easy=True)
    got: dict[str, Any] = {}
    if easy is not None:
        for key, value in easy.items():
            got[key] = value[0] if isinstance(value, list) and value else value
    title_ok = got.get("title") == get_track_title(track_meta)
    artist_ok = bool(got.get("artist"))
    album_ok = got.get("album") == album_meta.get("title")
    rec.record(
        "Embedded tags (title/artist/album)",
        title_ok and artist_ok and album_ok,
        f"title='{got.get('title')}', album='{got.get('album')}'",
    )
    rec.record(
        "Track number tagged",
        bool(got.get("tracknumber")),
        f"tracknumber={got.get('tracknumber')}",
    )

    raw = MutagenFile(str(produced))
    # 11. Embedded cover art (hard only when --embed-art requested).
    has_cover = False
    if raw is not None:
        if hasattr(raw, "pictures"):
            has_cover = bool(raw.pictures)
        elif raw.tags is not None:
            has_cover = any(k.startswith("APIC") for k in raw.tags)
    rec.record(
        "Embedded cover art",
        has_cover,
        "picture embedded" if has_cover else "none",
        hard=ctx["embed_art"],
    )

    # 12. ReplayGain tags (soft; depends on source availability).
    rg = False
    if raw is not None and raw.tags is not None:
        keys = {k.lower() for k in raw.tags}
        rg = "replaygain_track_gain" in keys
    rec.record(
        "ReplayGain tags",
        rg,
        "REPLAYGAIN_TRACK_GAIN present" if rg else "absent (source may lack RG)",
        hard=False,
    )

    # 13. Sidecar artifacts on disk.
    covers = list(out_dir.rglob("cover.jpg"))
    rec.record(
        "cover.jpg saved",
        bool(covers),
        f"{covers[0].stat().st_size // 1024} KB" if covers else "missing",
    )
    booklets = list(out_dir.rglob("booklet.pdf"))
    booklet_ok = bool(booklets) and booklets[0].stat().st_size > 0
    rec.record(
        "booklet.pdf saved",
        booklet_ok,
        f"{booklets[0].stat().st_size // 1024} KB" if booklets else "missing",
        hard=bool(booklet_url),
    )
    lrc = list(out_dir.rglob("*.lrc"))
    rec.record(
        "Lyrics sidecar (.lrc)",
        bool(lrc),
        lrc[0].name if lrc else "no lyrics for this track",
        hard=False,
    )


def build_config(url: str, quality: int) -> DownloadConfig:
    """Load the real user config with smoke-test feature flags enabled."""
    cli_options: dict[str, Any] = {
        "source_urls": [url],
        "quality": quality,
        "embed_art": True,
        "no_cover": False,
        "replaygain": True,
        "lyrics": True,
        "lyrics_mode": "both",
        "download_archive": False,
        "dry_run": False,
    }
    return ConfigManager(CONFIG_FILE).load_config(cli_options)


def print_summary(rec: Recorder) -> None:
    table = Table(title="qobuz-cli smoke test")
    table.add_column("Result", no_wrap=True)
    table.add_column("Check")
    table.add_column("Detail", overflow="fold")
    for name, ok, hard, detail in rec.results:
        if ok:
            status = "[green]PASS[/green]"
        elif hard:
            status = "[red]FAIL[/red]"
        else:
            status = "[yellow]SKIP[/yellow]"
        table.add_row(status, name, detail)
    console.print(table)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the qobuz-cli end-to-end smoke test."
    )
    parser.add_argument("url", nargs="?", default=DEFAULT_URL, help="Album/track URL.")
    parser.add_argument(
        "--quality",
        type=int,
        choices=[1, 2, 3, 4],
        default=2,
        help="1=MP3 320, 2=CD FLAC, 3=Hi-Res 96, 4=Hi-Res 192 (default: 2).",
    )
    parser.add_argument(
        "--keep",
        action="store_true",
        help="Keep the downloaded files instead of deleting the temp dir.",
    )
    args = parser.parse_args()

    if not CONFIG_FILE.is_file():
        console.print(
            f"[red]No configuration found at {CONFIG_FILE}.[/red] "
            "Run [cyan]qobuz-cli init <TOKEN>[/cyan] first."
        )
        return 2

    try:
        config = build_config(args.url, args.quality)
    except Exception as exc:
        console.print(f"[red]Failed to load configuration: {exc}[/red]")
        return 2

    if not config.token:
        console.print("[red]No auth token in configuration.[/red] Run init first.")
        return 2

    out_dir = Path(tempfile.mkdtemp(prefix="qcli-smoke-"))
    rec = Recorder()
    console.rule(f"[bold]Smoke test \u2192 {args.url}")
    console.print(f"[dim]Output dir: {out_dir}[/dim]\n")

    try:
        ctx = asyncio.run(run_live(config, args.url, out_dir, rec))
        if ctx is not None:
            validate_output(out_dir, ctx, rec)
    except Exception as exc:
        rec.record("Unexpected error", False, str(exc))
    finally:
        console.print()
        print_summary(rec)
        if args.keep:
            console.print(f"\n[dim]Files kept in {out_dir}[/dim]")
        else:
            shutil.rmtree(out_dir, ignore_errors=True)

    failures = rec.hard_failures()
    if failures:
        console.print(f"\n[bold red]\u2717 {failures} hard check(s) failed.[/bold red]")
        return 1
    console.print("\n[bold green]\u2713 All hard checks passed.[/bold green]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
