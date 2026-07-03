"""Tests for human-readable formatting helpers."""

import pytest

from qobuz_cli.utils.formatting import (
    extract_artist_name,
    format_duration,
    format_size,
    get_track_title,
)


@pytest.mark.parametrize(
    ("size", "expected"),
    [
        (0, "0 B"),
        (-5, "0 B"),
        (512, "512.0 B"),
        (1024, "1.0 KB"),
        (1536, "1.5 KB"),
        (1048576, "1.0 MB"),
    ],
)
def test_format_size(size, expected):
    assert format_size(size) == expected


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [
        (0, "0s"),
        (45, "45s"),
        (90, "1m 30s"),
        (3600, "1h"),
        (3725, "1h 2m 5s"),
    ],
)
def test_format_duration(seconds, expected):
    assert format_duration(seconds) == expected


def test_get_track_title_plain():
    assert get_track_title({"title": "Song"}) == "Song"


def test_get_track_title_appends_version():
    assert get_track_title({"title": "Song", "version": "Live"}) == "Song (Live)"


def test_get_track_title_skips_redundant_version():
    meta = {"title": "Song (Live)", "version": "Live"}
    assert get_track_title(meta) == "Song (Live)"


def test_extract_artist_name_direct():
    assert extract_artist_name({"name": "Artist"}) == "Artist"


def test_extract_artist_name_nested():
    assert extract_artist_name({"artist": {"name": "Nested"}}) == "Nested"


def test_extract_artist_name_fallback():
    assert extract_artist_name({}, fallback_id="42") == "Artist ID 42"
