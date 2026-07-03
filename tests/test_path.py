"""Tests for Qobuz URL parsing and path templating."""

import pytest

from qobuz_cli.utils.path import PathFormatter, parse_qobuz_url


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://www.qobuz.com/us-en/album/foo/abc123", ("album", "abc123")),
        ("https://open.qobuz.com/track/98765", ("track", "98765")),
        ("https://www.qobuz.com/us-en/interpreter/foo/55", ("artist", "55")),
    ],
)
def test_parse_qobuz_url(url, expected):
    assert parse_qobuz_url(url) == expected


def test_parse_qobuz_url_invalid():
    assert parse_qobuz_url("https://example.com/not-qobuz") is None


def test_resolve_conditionals():
    formatter = PathFormatter("unused")
    template = "%{?is_multidisc,CD{media_number}/|}{tracktitle}"
    result_true = formatter._resolve_conditionals(template, {"is_multidisc": 1})
    assert result_true == "CD{media_number}/{tracktitle}"
    result_false = formatter._resolve_conditionals(template, {"is_multidisc": 0})
    assert result_false == "{tracktitle}"
