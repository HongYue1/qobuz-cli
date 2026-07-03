"""Tests for ReplayGain tag construction from Qobuz audio_info."""

from qobuz_cli.media.tagger import build_replaygain_tags


def test_builds_gain_and_peak_tags():
    meta = {
        "audio_info": {
            "replaygain_track_gain": -10.53,
            "replaygain_track_peak": 0.999969,
        }
    }
    tags = build_replaygain_tags(meta)
    assert tags["REPLAYGAIN_TRACK_GAIN"] == "-10.53 dB"
    assert tags["REPLAYGAIN_TRACK_PEAK"] == "0.999969"


def test_missing_audio_info_returns_empty():
    assert build_replaygain_tags({}) == {}
    assert build_replaygain_tags({"audio_info": {}}) == {}


def test_partial_data_only_includes_present_fields():
    tags = build_replaygain_tags({"audio_info": {"replaygain_track_gain": 1.2}})
    assert tags == {"REPLAYGAIN_TRACK_GAIN": "1.20 dB"}


def test_string_numeric_values_are_coerced():
    meta = {
        "audio_info": {
            "replaygain_track_gain": "-8.4",
            "replaygain_track_peak": "0.5",
        }
    }
    tags = build_replaygain_tags(meta)
    assert tags["REPLAYGAIN_TRACK_GAIN"] == "-8.40 dB"
    assert tags["REPLAYGAIN_TRACK_PEAK"] == "0.500000"


def test_non_numeric_values_are_skipped():
    meta = {
        "audio_info": {"replaygain_track_gain": "n/a", "replaygain_track_peak": None}
    }
    assert build_replaygain_tags(meta) == {}
