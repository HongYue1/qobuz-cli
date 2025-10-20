"""
Utilities for handling file paths, templates, and URL parsing.
"""

import re
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from pathvalidate import sanitize_filename, sanitize_filepath

from qobuz_cli.utils.formatting import get_track_title


def parse_qobuz_url(url: str) -> Optional[Tuple[str, str]]:
    """
    Parses a Qobuz URL to extract the content type and ID.
    Handles multiple URL formats.
    """
    pattern = re.compile(
        r"qobuz\.com/(?:[^/]+/)?(?P<type>album|artist|track|playlist|label|interpreter)/(?:[^/]+/)?(?P<id>[\w\d-]+)"
    )
    match = pattern.search(url)
    if match:
        url_type = match.group("type")
        if url_type == "interpreter":
            url_type = "artist"
        return url_type, match.group("id")
    return None


def create_dir(directory_path: Path) -> None:
    """Creates a directory if it does not already exist."""
    directory_path.mkdir(parents=True, exist_ok=True)


class PathFormatter:
    """
    Formats an output path template string using track and album metadata.
    """

    def __init__(self, template: str) -> None:
        self.template = template

    def format_path(
        self,
        track_meta: Dict[str, Any],
        album_meta: Dict[str, Any],
        file_extension: str,
    ) -> Path:
        """
        Generates a final, sanitized file path from the template.
        """
        template_vars = self._get_template_vars(track_meta, album_meta, file_extension)
        formatted_str = self._resolve_conditionals(self.template, template_vars)
        final_str = formatted_str.format(**template_vars)
        return Path(sanitize_filepath(final_str, platform="auto"))

    def _resolve_conditionals(
        self, template_str: str, variables: Dict[str, Any]
    ) -> str:
        pattern = re.compile(r"%\{\?(\w+),([^|]*?)\|([^}]*?)\}")

        def replacer(match: re.Match) -> str:
            key, true_val, false_val = match.groups()
            return true_val if variables.get(key) else false_val

        return pattern.sub(replacer, template_str)

    def _get_template_vars(
        self, track_meta: Dict[str, Any], album_meta: Dict[str, Any], ext: str
    ) -> Dict[str, Any]:
        """Builds the variable dictionary for template formatting."""
        from qobuz_cli.media.tagger import PerformersParser

        # Instantiate the parser with both performers string and title to get all roles
        parser = PerformersParser(track_meta.get("performers"), track_meta.get("title"))

        # Get main artists, with a fallback to the performer field
        main_artists = parser.get_primary_artists() or [
            track_meta.get("performer", {}).get("name", "Unknown Artist")
        ]

        # Get all featured artists (from both performers string and title)
        featured_artists = parser.get_performers_by_role("Featured")

        # Combine them for the {artist} tag
        all_artists_list = list(dict.fromkeys(main_artists + featured_artists))

        # Build the {artist_featuring} tag string
        artist_featuring_str = main_artists[0] if main_artists else "Unknown Artist"
        if featured_artists:
            artist_featuring_str += f" (feat. {', '.join(featured_artists)})"

        return {
            "tracknumber": f"{track_meta.get('track_number', 0):02}",
            "tracktitle": sanitize_filename(get_track_title(track_meta)),
            "artist": sanitize_filename(
                ", ".join(all_artists_list) or "Unknown Artist"
            ),
            "artist_featuring": sanitize_filename(
                artist_featuring_str or "Unknown Artist"
            ),
            "albumartist": sanitize_filename(
                album_meta.get("artist", {}).get("name", "Unknown Artist")
            ),
            "album": sanitize_filename(album_meta.get("title", "Unknown Album")),
            "year": str(album_meta.get("release_date_original", "0"))[:4],
            "media_number": str(track_meta.get("media_number", 1)),
            "ext": ext,
            "is_multidisc": 1 if album_meta.get("media_count", 1) > 1 else 0,
            "composer": sanitize_filename(
                ", ".join(p for p in parser.get_performers_by_role("Composer") if p)
            ),
            "producer": sanitize_filename(
                ", ".join(p for p in parser.get_performers_by_role("Producer") if p)
            ),
        }
