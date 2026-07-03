"""Tests for LRCLIB lyrics extraction, mode handling, and sidecar writing."""

from qobuz_cli.media.lyrics import LyricsProvider, extract_lyrics_query


def test_extract_uses_track_performer_first():
    track = {"title": "Song", "performer": {"name": "Artist"}, "duration": 200}
    album = {"title": "Album", "artist": {"name": "Album Artist"}}
    artist, title, album_name, duration = extract_lyrics_query(track, album)
    assert artist == "Artist"
    assert title == "Song"
    assert album_name == "Album"
    assert duration == 200


def test_extract_falls_back_to_album_artist():
    track = {"title": "Song", "duration": 12.9}
    album = {"title": "Album", "artist": {"name": "Album Artist"}}
    artist, _title, _album, duration = extract_lyrics_query(track, album)
    assert artist == "Album Artist"
    assert duration == 12


def test_extract_handles_missing_fields():
    artist, title, album_name, duration = extract_lyrics_query({}, {})
    assert artist == ""
    assert title == ""
    assert album_name == ""
    assert duration is None


def test_mode_flags():
    embed = LyricsProvider("embed")
    assert (embed.embed, embed.write_lrc) == (True, False)
    lrc = LyricsProvider("lrc")
    assert (lrc.embed, lrc.write_lrc) == (False, True)
    both = LyricsProvider("both")
    assert (both.embed, both.write_lrc) == (True, True)


def test_unknown_mode_defaults_to_embed():
    provider = LyricsProvider("garbage")
    assert provider.mode == "embed"
    assert provider.embed is True
    assert provider.write_lrc is False


def test_write_sidecar_prefers_lrc_for_synced(tmp_path):
    provider = LyricsProvider("lrc")
    audio = tmp_path / "track.flac"
    audio.write_bytes(b"")
    assert provider._write_sidecar(str(audio), "[00:01.00]hi", None) is True
    assert (tmp_path / "track.lrc").read_text(encoding="utf-8") == "[00:01.00]hi"


def test_write_sidecar_uses_txt_for_plain(tmp_path):
    provider = LyricsProvider("lrc")
    audio = tmp_path / "track.flac"
    audio.write_bytes(b"")
    assert provider._write_sidecar(str(audio), None, "plain words") is True
    assert (tmp_path / "track.txt").read_text(encoding="utf-8") == "plain words"
