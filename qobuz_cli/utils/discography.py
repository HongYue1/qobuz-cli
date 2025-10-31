"""
Utility for intelligently filtering an artist's discography to avoid duplicates.
"""

import re
from difflib import SequenceMatcher
from typing import Any

# A similarity ratio of 90% is a good starting point for album titles.
# This allows for minor differences while preventing unrelated albums from grouping.
SIMILARITY_THRESHOLD = 0.90

# Pre-compile regexes for performance
TYPE_REGEXES = {
    "remaster": re.compile(r"\b(re-?master(ed)?)\b", re.IGNORECASE),
    "extra": re.compile(
        r"\b(anniversary|deluxe|live|collector|demo|expanded|remix|acoustic|instrumental|edition)\b",
        re.IGNORECASE,
    ),
}


def _is_type(album: dict[str, Any], album_type: str) -> bool:
    """Checks if an album title or version matches a given type (e.g., 'remaster')."""
    text = f"{album.get('title', '')} {album.get('version', '')}"
    return bool(TYPE_REGEXES[album_type].search(text))


def _get_base_title(album: dict[str, Any]) -> str:
    """Creates a normalized base title by removing extras for comparison."""
    title = album.get("title", "")
    # Remove content in parentheses/brackets for a cleaner base title
    return re.sub(r"[\(\[][^()\[\]]*[\)\]]", "", title).strip().lower()


def _find_best_version_in_group(
    group: list[dict[str, Any]], skip_extras: bool
) -> dict[str, Any]:
    """
    Takes a list of similar album versions and returns the single best one based on
    quality, remaster status, and release date.
    """
    # 1. Find the maximum audio quality (bit_depth, sampling_rate) in the group.
    best_quality = max(
        (v.get("maximum_bit_depth", 0), v.get("maximum_sampling_rate", 0))
        for v in group
    )

    # 2. Filter to get 'candidates' that match this quality.
    candidates = [
        v
        for v in group
        if (v.get("maximum_bit_depth", 0), v.get("maximum_sampling_rate", 0))
        == best_quality
    ]

    # 3. From candidates, create a 'preferred' list (non-remaster, non-extra).
    preferred_candidates = [
        c
        for c in candidates
        if not _is_type(c, "remaster") and not (skip_extras and _is_type(c, "extra"))
    ]

    # 4. Use 'preferred' if it's not empty, otherwise fall back to 'candidates'.
    selection_pool = preferred_candidates or candidates

    # 5. From the final selection pool, return the one with the newest
    # original release date.
    return max(selection_pool, key=lambda v: v.get("release_date_original", "0"))


def smart_discography_filter(
    items: list[dict[str, Any]], skip_extras: bool = True
) -> list[dict[str, Any]]:
    """
    Filters a list of album items to select the best version of each album using
    similarity clustering. This allows grouping of albums with minor title
    variations (e.g., "The Album" vs "Album (Deluxe Edition)").

    Args:
        items: A list of album metadata dictionaries from the Qobuz API.
        skip_extras: If True, attempts to filter out deluxe, live, and special editions
                     when a standard version is available.

    Returns:
        A filtered list containing the best version of each unique album.
    """
    if not items:
        return []

    # Filter out albums where the primary artist doesn't match (e.g., features)
    # This check is important to do upfront to ensure accurate clustering.
    requested_artist = items[0].get("artist", {}).get("name")
    if requested_artist:
        items = [
            item
            for item in items
            if item.get("artist", {}).get("name") == requested_artist
        ]

    # --- New Clustering Logic ---
    album_groups: list[list[dict[str, Any]]] = []
    for album in items:
        album_base_title = _get_base_title(album)
        found_a_group = False

        for group in album_groups:
            # Compare with the first item in the group as a representative
            representative_base_title = _get_base_title(group[0])

            ratio = SequenceMatcher(
                None, album_base_title, representative_base_title
            ).ratio()

            if ratio >= SIMILARITY_THRESHOLD:
                group.append(album)
                found_a_group = True
                break

        if not found_a_group:
            # No similar group found, so start a new one.
            album_groups.append([album])

    # --- Final Selection ---
    final_list = []
    for group in album_groups:
        # Use the helper to find the best version within the clustered group
        best_version = _find_best_version_in_group(group, skip_extras)
        final_list.append(best_version)

    return final_list
