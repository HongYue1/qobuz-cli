"""Tests for the DownloadConfig validation model."""

import pytest
from pydantic import ValidationError

from qobuz_cli.models.config import (
    DownloadConfig,
    get_quality_info,
    resolve_download_format,
)


def test_valid_config(config_factory):
    config = DownloadConfig(**config_factory())
    assert config.app_id == "123456789"


@pytest.mark.parametrize(
    ("user_code", "api_code"),
    [(1, 5), (2, 6), (3, 7), (4, 27)],
)
def test_quality_user_code_maps_to_api_code(config_factory, user_code, api_code):
    config = DownloadConfig(**config_factory(quality=user_code))
    assert config.quality == api_code


@pytest.mark.parametrize("api_code", [5, 6, 7, 27])
def test_quality_accepts_direct_api_codes(config_factory, api_code):
    config = DownloadConfig(**config_factory(quality=api_code))
    assert config.quality == api_code


def test_quality_rejects_invalid_value(config_factory):
    with pytest.raises(ValidationError):
        DownloadConfig(**config_factory(quality=99))


@pytest.mark.parametrize("workers", [0, 33])
def test_workers_out_of_range_rejected(config_factory, workers):
    with pytest.raises(ValidationError):
        DownloadConfig(**config_factory(max_workers=workers))


def test_template_requires_track_placeholder(config_factory):
    with pytest.raises(ValidationError):
        DownloadConfig(**config_factory(output_template="{album}/{artist}"))


def test_template_rejects_path_traversal(config_factory):
    with pytest.raises(ValidationError):
        DownloadConfig(**config_factory(output_template="../{tracktitle}"))


def test_template_rejects_unknown_placeholder(config_factory):
    with pytest.raises(ValidationError):
        DownloadConfig(**config_factory(output_template="{tracktitle}/{bogus}"))


def test_auth_required(config_factory):
    kwargs = config_factory(token="")
    with pytest.raises(ValidationError):
        DownloadConfig(**kwargs)


def test_email_password_is_valid_auth(config_factory):
    kwargs = config_factory(token="", email="user@example.com", password="pwhash")
    config = DownloadConfig(**kwargs)
    assert config.email == "user@example.com"


@pytest.mark.parametrize("app_id", ["12345", "1234567890", "12345678x"])
def test_app_id_must_be_nine_digits(config_factory, app_id):
    with pytest.raises(ValidationError):
        DownloadConfig(**config_factory(app_id=app_id))


def test_conflicting_cover_options(config_factory):
    with pytest.raises(ValidationError):
        DownloadConfig(**config_factory(no_cover=True, embed_art=True))


def test_get_ini_keys_excludes_internal_fields():
    keys = DownloadConfig.get_ini_keys()
    assert "config_path" not in keys
    assert "source_urls" not in keys
    assert "quality" in keys


def test_get_quality_info_known_and_unknown():
    assert get_quality_info(6)["ext"] == "flac"
    assert get_quality_info(999)["name"] == "Unknown"


class TestResolveDownloadFormat:
    """Smart quality fallback: resolving the actually-delivered format."""

    def test_uses_returned_format_when_available(self):
        fmt, downgraded = resolve_download_format(27, {"format_id": 27})
        assert fmt == 27
        assert downgraded is False

    def test_detects_downgrade_and_returns_actual_format(self):
        url_data = {
            "format_id": 6,
            "restrictions": [{"code": "FormatRestrictedByFormatAvailability"}],
        }
        fmt, downgraded = resolve_download_format(27, url_data)
        assert fmt == 6
        assert downgraded is True

    def test_missing_format_id_falls_back_to_requested(self):
        fmt, downgraded = resolve_download_format(7, {})
        assert fmt == 7
        assert downgraded is False

    def test_unrelated_restriction_is_not_a_downgrade(self):
        url_data = {"format_id": 6, "restrictions": [{"code": "SomethingElse"}]}
        fmt, downgraded = resolve_download_format(6, url_data)
        assert fmt == 6
        assert downgraded is False
