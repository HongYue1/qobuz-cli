"""
Functions for formatting and displaying data in the console using Rich.
"""

from pathlib import Path
from typing import Any, Dict, Optional

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from qobuz_cli.models.config import DownloadConfig, QUALITY_MAP
from qobuz_cli.models.stats import DownloadStats
from qobuz_cli.utils.formatting import format_duration, format_size


def format_error_with_suggestions(error: Exception, context: Dict = None) -> Panel:
    """Formats an error with actionable suggestions into a Rich Panel."""
    error_type = type(error).__name__
    error_msg = str(error)

    suggestions_map = {
        "AuthenticationError": [
            "• Verify your credentials in the configuration file.",
            "• Your token may have expired. Run `qobuz-cli init` again.",
            "• Check your account status on play.qobuz.com.",
        ],
        "InvalidAppSecretError": [
            "• Qobuz may have updated their web player.",
            "• Run `qobuz-cli init --force` to refresh API secrets.",
        ],
        "NotStreamableError": [
            "• This content may not be available in your region.",
            "• Your subscription tier may not grant access.",
            "• Try a different quality with the -q flag.",
        ],
        "CircuitBreakerError": [
            "• The app has detected too many API failures and is cooling down.",
            "• Check your internet connection.",
            "• Reduce `--workers` if you are being rate-limited.",
        ],
        "ClientResponseError": [
            "• A network connection issue occurred.",
            "• The Qobuz API might be temporarily unavailable.",
            "• Please try again in a few minutes.",
        ],
        "TimeoutError": [
            "• A download timed out, which may indicate network throttling.",
            "• Check your internet speed.",
            "• Try reducing the number of `--workers`.",
        ],
    }

    suggestions = suggestions_map.get(
        error_type, ["• Run the command with -vv for detailed logs."]
    )

    error_text = Text()
    error_text.append(f"{error_type}: ", style="bold red")
    error_text.append(error_msg)

    suggestion_text = Text("\n".join(suggestions))

    content = Table.grid(padding=(1, 0))
    content.add_row(error_text)
    content.add_row()
    content.add_row(Text("Suggestions", style="bold yellow"))
    content.add_row(suggestion_text)

    if context:
        content.add_row()
        content.add_row(Text(f"Context: {context}", style="dim"))

    return Panel(
        content,
        title="[bold red]An Error Occurred[/bold red]",
        border_style="red",
        expand=False,
    )


def print_config(config_path: Path, config_data: Dict[str, Any]):
    """Displays the current configuration, hiding sensitive data."""
    console = Console()
    content = ""
    for key, value in config_data.items():
        if key in ("token", "password", "secrets"):
            value = "[hidden]"
        elif isinstance(value, list):
            value = ", ".join(value)
        content += f"{key} = {value}\n"

    console.print(
        Panel(
            content.strip(),
            title=f"Configuration ([dim]{config_path}[/dim])",
            border_style="cyan",
        )
    )


def print_validation_table(config: DownloadConfig):
    """Displays a summary of the current settings."""
    console = Console()
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column(style="bold cyan")
    table.add_column()

    auth_method = "Token" if config.token else "Email/Password"
    quality_name = QUALITY_MAP.get(config.quality, {}).get("name", "Unknown")
    table.add_row("Auth Method:", f"[green]{auth_method}[/green]")
    table.add_row("Quality:", quality_name)
    table.add_row("Max Workers:", str(config.max_workers))
    table.add_row(
        "Download Archive:", "✓ Enabled" if config.download_archive else "✗ Disabled"
    )
    table.add_row(
        "Smart Discography:", "✓ Enabled" if config.smart_discography else "✗ Disabled"
    )
    table.add_row("Output Template:", f"[dim]{config.output_template}[/dim]")

    console.print(
        Panel(
            table,
            title="[bold green]✓ Validated Settings[/bold green]",
            border_style="green",
        )
    )


def print_stats_table(stats_data: Dict[str, Any]):
    """Displays download archive statistics."""
    console = Console()
    console.print(
        f"\n[bold]Total Tracks in Archive:[/] [green]{stats_data['total_tracks']}[/green]\n"
    )

    if top_artists := stats_data.get("top_artists"):
        table = Table(title="Top 10 Artists")
        table.add_column("Rank", style="dim")
        table.add_column("Artist", style="cyan")
        table.add_column("Tracks", justify="right", style="green")
        for i, (artist, count) in enumerate(top_artists, 1):
            table.add_row(str(i), artist, str(count))
        console.print(table)
    else:
        console.print("[dim]No artist data in archive yet.[/dim]")


def print_summary_panel(
    stats: DownloadStats, duration_s: float, progress_stats: Optional[Dict] = None
):
    """Displays an enhanced final summary of the download session."""
    console = Console()

    # Main statistics table
    stats_table = Table(show_header=False, box=None, padding=(0, 2))
    stats_table.add_column(style="bold cyan", justify="right", width=20)
    stats_table.add_column(style="white", justify="left")

    # Success metrics
    stats_table.add_row(
        "✓ Downloaded:", f"[bold green]{stats.tracks_downloaded}[/bold green]"
    )

    # Skip metrics (only show if non-zero)
    skip_sections = []
    if stats.tracks_skipped_archive > 0:
        skip_sections.append(
            f"[yellow]{stats.tracks_skipped_archive} (archive)[/yellow]"
        )
    if stats.tracks_skipped_exists > 0:
        skip_sections.append(f"[yellow]{stats.tracks_skipped_exists} (exists)[/yellow]")
    if stats.tracks_skipped_quality > 0:
        skip_sections.append(
            f"[yellow]{stats.tracks_skipped_quality} (quality)[/yellow]"
        )

    if skip_sections:
        stats_table.add_row("○ Skipped:", " + ".join(skip_sections))

    # Albums skipped (not streamable)
    if hasattr(stats, "albums_skipped") and stats.albums_skipped > 0:
        stats_table.add_row(
            "⚠ Albums Not Available:", f"[yellow]{stats.albums_skipped}[/yellow]"
        )

    # Failure metrics
    if stats.tracks_failed > 0:
        stats_table.add_row("✗ Failed:", f"[bold red]{stats.tracks_failed}[/bold red]")

    stats_table.add_row("", "")  # Spacer

    # Size and speed metrics
    stats_table.add_row(
        "Total Size:", f"[cyan]{format_size(stats.total_size_downloaded)}[/cyan]"
    )

    avg_speed = stats.total_size_downloaded / duration_s if duration_s > 0 else 0
    stats_table.add_row(
        "Avg. Speed:", f"[magenta]{format_size(int(avg_speed))}/s[/magenta]"
    )

    if stats.peak_speed_bps > 0:
        stats_table.add_row(
            "Peak Speed:",
            f"[magenta]{format_size(int(stats.peak_speed_bps))}/s[/magenta]",
        )

    stats_table.add_row("Time Elapsed:", f"[blue]{format_duration(duration_s)}[/blue]")

    # Concurrency metrics (if available from progress manager)
    if progress_stats:
        stats_table.add_row("", "")  # Spacer
        stats_table.add_row(
            "Peak Concurrent:",
            f"[green]{progress_stats.get('peak_concurrent', 0)}[/green]",
        )

    # Performance metrics
    if stats.tracks_downloaded > 0 and duration_s > 0:
        tracks_per_minute = (stats.tracks_downloaded / duration_s) * 60
        stats_table.add_row(
            "Throughput:", f"[cyan]{tracks_per_minute:.1f} tracks/min[/cyan]"
        )

    # Create title based on mode
    if stats.dry_run:
        title = "🔍 [bold]Dry Run Summary[/bold]"
        border_color = "yellow"
    else:
        title = "🎵 [bold]Download Complete![/bold]"
        border_color = "green"

    console.print()
    console.print(
        Panel(
            stats_table,
            title=title,
            border_style=border_color,
            box=box.DOUBLE,
            expand=False,
            padding=(1, 2),
        )
    )

    console.print()
