"""
Utility for intelligently filtering an artist's discography to avoid duplicates.
"""

import re
from typing import Any, Dict, List


def smart_discography_filter(
    items: List[Dict[str, Any]], skip_extras: bool = True
) -> List[Dict[str, Any]]:
    """
    Filters a list of album items to select the best version of each album.

    This is an enhanced version that prioritizes non-remasters and non-specials
    (like 'deluxe', 'live', etc.) unless they are the only option available.

    Args:
        items: A list of album metadata dictionaries from the Qobuz API.
        skip_extras: If True, attempts to filter out deluxe, live, and special editions.

    Returns:
        A filtered list of album dictionaries.
    """
    if not items:
        return []

    # --- THIS IS THE FIX ---
    # The simple max-quality filter has been replaced with the more intelligent
    # logic from the original codebase to better handle remasters and special editions.
    TYPE_REGEXES = {
        "remaster": re.compile(r"\b(re-?master(ed)?)\b", re.IGNORECASE),
        "extra": re.compile(
            r"\b(anniversary|deluxe|live|collector|demo|expanded|remix|acoustic|instrumental|edition)\b",
            re.IGNORECASE,
        ),
    }

    def is_type(album: Dict[str, Any], album_type: str) -> bool:
        text = f"{album.get('title', '')} {album.get('version', '')}"
        return bool(TYPE_REGEXES[album_type].search(text))

    def get_base_title(album: Dict[str, Any]) -> str:
        title = album.get("title", "")
        # Remove content in parentheses/brackets for a cleaner base title
        return re.sub(r"[\(\[][^()\[\]]*[\)\]]", "", title).strip().lower()

    # Group albums by their base title
    albums_by_title: Dict[str, List[Dict[str, Any]]] = {}
    requested_artist = items[0].get("artist", {}).get("name")
    for item in items:
        # Filter out albums where the primary artist doesn't match (e.g., features)
        if item.get("artist", {}).get("name") == requested_artist:
            base_title = get_base_title(item)
            albums_by_title.setdefault(base_title, []).append(item)

    final_list = []
    for versions in albums_by_title.values():
        if not versions:
            continue

        # Find the best available quality (bit depth then sampling rate)
        best_quality = max(
            (v.get("maximum_bit_depth", 0), v.get("maximum_sampling_rate", 0))
            for v in versions
        )

        # Filter down to only albums matching the best quality
        candidates = [
            v
            for v in versions
            if (v.get("maximum_bit_depth", 0), v.get("maximum_sampling_rate", 0))
            == best_quality
        ]

        preferred_candidates = [
            c
            for c in candidates
            if not is_type(c, "remaster") and not (skip_extras and is_type(c, "extra"))
        ]

        # If we have preferred versions (e.g., original, standard editions), use them.
        # Otherwise, fall back to the best-quality candidates we have.
        selection_pool = preferred_candidates or candidates

        # From the best available options, pick the most recently released one.
        best_version = max(
            selection_pool, key=lambda v: v.get("release_date_original", "0")
        )
        final_list.append(best_version)

    return final_list
