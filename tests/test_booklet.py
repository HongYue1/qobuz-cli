"""Tests for digital-booklet URL extraction from Qobuz album metadata."""

from qobuz_cli.core.track_processor import extract_booklet_url


def test_returns_booklet_url_for_format_21():
    album = {"goodies": [{"file_format_id": 21, "url": "https://x/b.pdf"}]}
    assert extract_booklet_url(album) == "https://x/b.pdf"


def test_ignores_non_booklet_goodies():
    album = {"goodies": [{"file_format_id": 5, "url": "https://x/other"}]}
    assert extract_booklet_url(album) is None


def test_returns_none_when_url_missing():
    album = {"goodies": [{"file_format_id": 21}]}
    assert extract_booklet_url(album) is None


def test_returns_none_when_no_goodies():
    assert extract_booklet_url({}) is None
    assert extract_booklet_url({"goodies": None}) is None
    assert extract_booklet_url({"goodies": []}) is None


def test_picks_booklet_among_multiple_goodies():
    album = {
        "goodies": [
            {"file_format_id": 5, "url": "https://x/other"},
            {"file_format_id": 21, "url": "https://x/booklet.pdf"},
        ]
    }
    assert extract_booklet_url(album) == "https://x/booklet.pdf"
