"""
Defines the command-line interface for the application using Typer.
Enhanced with stdin URL processing support.
"""

import asyncio
import hashlib
import logging
import os
import sys
import time
from pathlib import Path

import typer
from rich.console import Console
from rich.logging import RichHandler

from qobuz_cli import __version__
from qobuz_cli.api.client import QobuzAPIClient
from qobuz_cli.core.download_manager import DownloadManager
from qobuz_cli.exceptions import QobuzCliError
from qobuz_cli.media.downloader import close_connection_pool
from qobuz_cli.storage.archive import TrackArchive
from qobuz_cli.storage.config_manager import ConfigManager
from qobuz_cli.web.bundle_fetcher import BundleFetcher

from .formatters import (
    print_config,
    print_output_template_help,
    print_stats_table,
    print_summary_panel,
    print_validation_table,
)
from .progress_manager import ProgressManager

console = Console()

logging.basicConfig(
    level="INFO",
    format="%(message)s",
    datefmt="[%X]",
    handlers=[
        RichHandler(
            console=console,
            rich_tracebacks=True,
            show_path=False,
            show_level=False,
            markup=True,
        )
    ],
)
log = logging.getLogger("qobuz_cli")

app = typer.Typer(
    name="qobuz-cli",
    help=(
        "A fast, modern, and concurrent music downloader from Qobuz. Use 'qcli"
        " <command> --help' for more info."
    ),
    rich_markup_mode="rich",
    pretty_exceptions_show_locals=False,
    add_completion=False,
)


def get_config_dir() -> Path:
    if os.name == "nt":
        base_dir = Path(os.getenv("APPDATA", "~\\AppData\\Roaming"))
    else:
        base_dir = Path(os.getenv("XDG_CONFIG_HOME", "~/.config"))
    return base_dir.expanduser() / "qobuz-cli"


CONFIG_DIR = get_config_dir()
CONFIG_FILE = CONFIG_DIR / "config.ini"


@app.callback(invoke_without_command=True)
def main_callback(
    ctx: typer.Context,
    verbose: int = typer.Option(
        0,
        "--verbose",
        "-v",
        count=True,
        help="Increase logging verbosity (-vv for debug).",
    ),
    version: bool = typer.Option(
        False, "--version", help="Show version and exit.", is_eager=True
    ),
    show_config: bool = typer.Option(
        False, "--show-config", help="Display the current configuration."
    ),
    output_help: bool = typer.Option(
        False,
        "--output-help",
        help="Show detailed help for formatting the output path and exit.",
        is_eager=True,
    ),
    clear_cache: bool = typer.Option(
        False, "--clear-cache", help="Clear the metadata cache and exit."
    ),
):
    """Qobuz Downloader CLI"""
    if output_help:
        print_output_template_help()
        raise typer.Exit()

    if version:
        console.print(f"[bold]qobuz-cli[/bold] version [cyan]{__version__}[/cyan]")
        raise typer.Exit()

    log_level = "INFO"
    if verbose >= 2:
        log_level = "DEBUG"
    logging.getLogger("qobuz_cli").setLevel(log_level)

    if clear_cache:
        from qobuz_cli.storage.cache import CacheManager

        cache = CacheManager(CONFIG_DIR)
        console.print("[cyan]Clearing metadata cache...[/cyan]")

        cache_files_before = list(cache.cache_dir.glob("*.json"))
        files_count = len(cache_files_before)

        if cache.clear():
            console.print(
                f"[green]✓ Cache cleared successfully ({files_count} entries removed"
                ").[/green]"
            )
        else:
            console.print("[red]✗ Failed to clear cache.[/red]")
        raise typer.Exit()

    if show_config:
        if not CONFIG_FILE.is_file():
            console.print(
                "[red]✗ Config file not found.[/] Run [cyan]qobuz-cli init[/cyan]"
                " first."
            )
            raise typer.Exit(code=1)
        config_manager = ConfigManager(CONFIG_FILE)
        config_data = config_manager._get_config_as_dict()
        print_config(CONFIG_FILE, config_data)
        raise typer.Exit()

    if ctx.invoked_subcommand is None:
        console.print(ctx.get_help())


@app.command()
def init(
    credentials: list[str] = typer.Argument(  # noqa: B008
        ...,
        help="Authentication token OR email and password.",
        metavar="<TOKEN> | <EMAIL> <PASSWORD>",
    ),
    force: bool = typer.Option(
        False, "--force", "-f", help="Overwrite existing credentials without asking."
    ),
):
    """Initialize configuration with Qobuz credentials."""
    if (
        CONFIG_FILE.exists()
        and not force
        and not typer.confirm(
            "Configuration file already exists. Overwrite the credentials?"
        )
    ):
        raise typer.Abort()

    async def _init_async():
        console.print("\n[cyan]Fetching API secrets from Qobuz web player...[/cyan]")
        try:
            bundle = await BundleFetcher.fetch()
            app_id = bundle.extract_app_id()
            secrets = list(bundle.extract_secrets().values())
            console.print("[green]✓ Secrets fetched successfully.[/green]")
        except Exception as e:
            console.print(f"[red]✗ Failed to fetch secrets: {e}[/red]")
            raise typer.Exit(code=1) from e
        settings = {"app_id": app_id, "secrets": secrets}
        if len(credentials) == 1:
            settings["token"] = credentials[0]
            console.print("[green]✓ Using token authentication.[/green]")
        elif len(credentials) == 2:
            settings["email"] = credentials[0]
            settings["password"] = hashlib.md5(credentials[1].encode()).hexdigest()  # noqa: S324
            console.print("[green]✓ Using email/password authentication.[/green]")
        else:
            console.print(
                "[red]✗ Invalid credentials provided. "
                "Use a token or email + password.[/red]"
            )
            raise typer.Exit(code=1)
        config_manager = ConfigManager(CONFIG_FILE)
        config_manager.save_new_config(settings)
        console.print(
            f"\n[bold green]✓ Configuration saved to '{CONFIG_FILE}'[/bold green]"
        )
        console.print("Ready to download! Try: [cyan]qobuz-cli download <URL>[/cyan]")

    asyncio.run(_init_async())


def _read_urls_from_stdin() -> list[str]:
    """Reads URLs from stdin, one per line."""
    if sys.stdin.isatty():
        console.print(
            "[yellow]⚠️  No input detected on stdin. Please pipe URLs or redirect"
            " a file.[/yellow]"
        )
        console.print(
            "[dim]Examples:[/dim]\n"
            "  [cyan]cat urls.txt | qcli download --stdin[/cyan]\n"
            "  [cyan]qcli download --stdin < urls.txt[/cyan]\n"
            "  [cyan]echo 'https://...' | qcli download --stdin[/cyan]"
        )
        raise typer.Exit(code=1)

    urls = []
    console.print("[dim]Reading URLs from stdin...[/dim]")
    try:
        for line in sys.stdin:
            line = line.strip()
            if line and not line.startswith("#"):
                urls.append(line)
    except KeyboardInterrupt:
        console.print("\n[yellow]⚠️  Input interrupted.[/yellow]")
        raise typer.Exit(code=1) from None

    if not urls:
        console.print("[yellow]⚠️  No valid URLs found in stdin.[/yellow]")
        raise typer.Exit(code=1)

    console.print(f"[green]✓ Read {len(urls)} URLs from stdin.[/green]")
    return urls


@app.command(name="download")
def download_command(
    urls: list[str] | None = typer.Argument(  # noqa: B008
        None, help="One or more Qobuz URLs or paths to files containing URLs."
    ),
    # --- Core Download Options ---
    quality: int | None = typer.Option(
        None,
        "-q",
        "--quality",
        help=(
            "Set quality. 1: MP3 320, 2: CD (16/44.1), 3: Hi-Res (24/96), "
            "4: Hi-Res+ (24/192)."
        ),
    ),
    output_template: str | None = typer.Option(
        None,
        "-o",
        "--output",
        help="Define the download path. Use qcli --output-help for all placeholders.",
    ),
    workers: int | None = typer.Option(
        None,
        "-w",
        "--workers",
        help=(
            "Number of simultaneous downloads (default 8, override default in config)."
        ),
    ),
    # --- File & Artwork Options ---
    embed_art: bool | None = typer.Option(
        None,
        "--embed-art/--no-embed-art",
        help="Save the cover art inside the audio file's metadata.",
    ),
    no_cover: bool | None = typer.Option(
        None,
        "--no-cover/--cover",
        help="Do not save the separate 'cover.jpg' file.",
    ),
    og_cover: bool | None = typer.Option(
        None,
        "--og-cover/--no-og-cover",
        help="Download cover art in its original resolution (not 600x600).",
    ),
    no_m3u: bool | None = typer.Option(
        None,
        "--no-m3u/--m3u",
        help="Do not create a .m3u playlist file when downloading a playlist.",
    ),
    # --- Content Filtering Options ---
    no_fallback: bool | None = typer.Option(
        None,
        "--no-fallback/--fallback",
        help="Skip tracks if requested quality is unavailable (no downgrading).",
    ),
    smart_discography: bool | None = typer.Option(
        None,
        "-s",
        "--smart/--no-smart",
        help="Filter discographies to remove duplicate albums (remasters, etc.).",
    ),
    albums_only: bool | None = typer.Option(
        None,
        "--albums-only/--all-releases",
        help="Download only full albums from discographies (skip singles/EPs).",
    ),
    # --- Behavior & Utility Options ---
    download_archive: bool | None = typer.Option(
        None,
        "--archive/--no-archive",
        help="Keep a record of downloaded tracks to avoid re-downloading them.",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Simulate the download process without writing any files.",
    ),
    stdin: bool = typer.Option(
        False, "--stdin", help="Read URLs from standard input, one URL per line."
    ),
):
    """Download music from Qobuz."""
    if stdin and urls:
        console.print(
            "[yellow]⚠️  Both URLs and --stdin provided. Using --stdin only.[/yellow]"
        )
        urls = _read_urls_from_stdin()
    elif stdin:
        urls = _read_urls_from_stdin()
    elif not urls:
        console.print(
            "[red]✗ No URLs provided.[/red] "
            "Use: [cyan]qcli download <URL>[/cyan] or [cyan]--stdin[/cyan]"
        )
        raise typer.Exit(code=1)

    cli_options = {
        key: value
        for key, value in {
            "source_urls": urls,
            "quality": quality,
            "output_template": output_template,
            "max_workers": workers,
            "embed_art": embed_art,
            "no_cover": no_cover,
            "og_cover": og_cover,
            "albums_only": albums_only,
            "no_m3u": no_m3u,
            "no_fallback": no_fallback,
            "smart_discography": smart_discography,
            "download_archive": download_archive,
            "dry_run": dry_run,
        }.items()
        if value is not None
    }
    if "dry_run" not in cli_options:
        cli_options["dry_run"] = dry_run

    async def _download_async():
        api_client = None
        manager = None
        duration = 0
        progress_stats = None

        dry_run_mode = cli_options.get("dry_run", False)

        async with ProgressManager(
            console=console, dry_run=dry_run_mode
        ) as progress_manager:
            try:
                config_manager = ConfigManager(CONFIG_FILE)
                config = config_manager.load_config(cli_options)

                api_client = QobuzAPIClient(
                    config.app_id, config.secrets, config.max_workers
                )

                if config.token:
                    await api_client.authenticator.authenticate_with_token(config.token)
                else:
                    await api_client.authenticator.authenticate_with_credentials(
                        config.email, config.password
                    )

                archive = TrackArchive(CONFIG_DIR)
                manager = DownloadManager(config, api_client, archive, progress_manager)

                if dry_run_mode:
                    console.print(
                        "[bold cyan]🎵 Starting dry run session...[/bold cyan]"
                    )
                else:
                    console.print(
                        "[bold cyan]🎵 Starting download session...[/bold cyan]"
                    )

                start_time = time.monotonic()

                try:
                    await manager.execute_downloads()
                except Exception as e:
                    log.error(f"[red]Error during downloads: {e}[/red]", exc_info=True)

                duration = time.monotonic() - start_time
                progress_stats = progress_manager.get_statistics()

            except QobuzCliError as e:
                console.print(f"[bold red]Error: {e}[/bold red]")
                raise typer.Exit(code=1) from e
            except Exception as e:
                console.print(f"[bold red]Unexpected error: {e}[/bold red]")
                log.debug("Full traceback:", exc_info=True)
                raise typer.Exit(code=1) from e
            finally:
                await close_connection_pool()
                if api_client:
                    await api_client.close()

        if manager:
            print_summary_panel(manager.stats, duration, progress_stats)
            if not manager.config.dry_run:
                manager.save_session_stats()

    asyncio.run(_download_async())


@app.command()
def validate():
    """Validate the current configuration."""
    try:
        config_manager = ConfigManager(CONFIG_FILE)
        config = config_manager.load_config()
        print_validation_table(config)
    except QobuzCliError as e:
        console.print(f"[red]✗ Configuration is invalid: {e}[/red]")
        raise typer.Exit(code=1) from e


@app.command()
def stats():
    """Show statistics from the download archive."""

    async def _get_stats():
        try:
            archive = TrackArchive(CONFIG_DIR)
            stats_data = await archive.get_stats()
            if stats_data:
                print_stats_table(stats_data)
            else:
                console.print("[yellow]Could not retrieve stats.[/yellow]")
        except Exception as e:
            console.print(f"[red]Error accessing archive: {e}[/red]")

    asyncio.run(_get_stats())


@app.command()
def vacuum():
    """Optimize the download archive database."""

    async def _vacuum():
        console.print("[cyan]Optimizing archive database...[/cyan]")
        archive = TrackArchive(CONFIG_DIR)
        if await archive.vacuum():
            console.print("[green]✓ Database optimized.[/green]")
        else:
            console.print("[red]✗ Optimization failed.[/red]")

    asyncio.run(_vacuum())


@app.command(name="clear-archive")
def clear_archive(
    force: bool = typer.Option(
        False,
        "--force",
        "-f",
        help="Bypass the confirmation prompt.",
    ),
):
    """Clear the entire download archive database."""
    if not force and not typer.confirm(
        "Are you sure you want to clear the entire download archive? "
        "This action will erase your download history and cannot be undone."
    ):
        console.print("[yellow]Operation cancelled.[/yellow]")
        raise typer.Abort()

    async def _clear_archive_async():
        console.print("[cyan]Clearing download archive...[/cyan]")
        archive = TrackArchive(CONFIG_DIR)
        if await archive.clear():
            console.print("[green]✓ Download archive cleared successfully.[/green]")
        else:
            console.print("[red]✗ Failed to clear download archive.[/red]")

    asyncio.run(_clear_archive_async())


@app.command()
def diagnose():
    """Diagnose common configuration and connectivity issues."""
    console.print("\n[bold cyan]Running diagnostics...[/bold cyan]\n")
    issues_found = False
    if CONFIG_FILE.is_file():
        console.print(f"[green]✓[/] Config file exists at: [dim]{CONFIG_FILE}[/dim]")
    else:
        console.print(
            "[red]✗ Config file not found.[/] Run [cyan]qobuz-cli init[/cyan]."
        )
        raise typer.Exit(code=1)
    try:
        config_manager = ConfigManager(CONFIG_FILE)
        config = config_manager.load_config()
        console.print("[green]✓[/] Configuration file is valid and can be loaded.")
        if not config.app_id or not config.secrets:
            console.print("[red]✗ App ID or secrets are missing.[/] Run `init` again.")
            issues_found = True
        else:
            console.print("[green]✓[/] App ID and secrets are present.")
    except QobuzCliError as e:
        console.print(f"[red]✗ Configuration validation failed: {e}[/red]")
        issues_found = True
    console.print("\n[dim]Testing connectivity to Qobuz servers...[/dim]")

    async def test_connection():
        import aiohttp

        try:
            timeout = aiohttp.ClientTimeout(total=10)
            async with (
                aiohttp.ClientSession(timeout=timeout) as session,
                session.get("https://play.qobuz.com") as resp,
            ):
                if resp.status == 200:
                    console.print("[green]✓[/] Successfully connected to Qobuz.")
                    return True
                console.print(
                    f"[red]✗ Could not connect to Qobuz (Status: {resp.status}).[/red]"
                )
                return False
        except Exception as e:
            console.print(f"[red]✗ Connection test failed: {e}[/red]")
            return False

    if not asyncio.run(test_connection()):
        issues_found = True
    console.print()
    if not issues_found:
        console.print(
            "[bold green]✓ All checks passed! Your setup looks good.[/bold green]\n"
        )
    else:
        console.print(
            "[bold red]✗ Some issues were found. "
            "Please review the messages above.[/bold red]\n"
        )
