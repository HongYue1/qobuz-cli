"""
Helper functions for formatting data into human-readable strings.
"""

from typing import Any


def format_size(bytes_size: int) -> str:
    """Formats bytes into a human-readable size string (e.g., '145.3 MB')."""
    if bytes_size <= 0:
        return "0 B"
    units = ["B", "KB", "MB", "GB", "TB"]
    i = 0
    while bytes_size >= 1024 and i < len(units) - 1:
        bytes_size /= 1024
        i += 1
    return f"{bytes_size:.1f} {units[i]}"


def format_duration(seconds: float) -> str:
    """
    Formats a duration in seconds into a human-readable string (e.g., '2h 34m 12s').
    """
    s = int(seconds)
    hours, remainder = divmod(s, 3600)
    minutes, secs = divmod(remainder, 60)
    parts = []
    if hours > 0:
        parts.append(f"{hours}h")
    if minutes > 0:
        parts.append(f"{minutes}m")
    if secs > 0 or not parts:
        parts.append(f"{secs}s")
    return " ".join(parts)


def get_track_title(track_meta: dict[str, Any]) -> str:
    """Constructs a full track title including its version, if available."""
    title = track_meta.get("title", "Unknown Title")
    if (version := track_meta.get("version")) and version.lower() not in title.lower():
        title = f"{title} ({version})"
    return title


def extract_artist_name(
    api_response: dict[str, Any], fallback_id: str | None = None
) -> str:
    """
    Extracts an artist's name from various possible API response structures.

    Args:
        api_response: The dictionary from a Qobuz API call.
        fallback_id: An ID to use if no name can be found.

    Returns:
        The extracted artist name or a fallback identifier.
    """
    if name := api_response.get("name"):
        return name
    if (artist := api_response.get("artist")) and (name := artist.get("name")):
        return name
    if (
        (albums := api_response.get("albums", {}).get("items"))
        and albums
        and (artist := albums[0].get("artist", {}).get("name"))
    ):
        return artist
    return f"Artist ID {fallback_id or api_response.get('id', 'Unknown')}"
