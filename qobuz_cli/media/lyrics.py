"""Fetches song lyrics from LRCLIB and applies them to downloaded tracks."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

import aiohttp
import mutagen.id3 as id3
from mutagen.flac import FLAC
from mutagen.id3 import ID3NoHeaderError

from qobuz_cli.media.downloader import get_connection_pool

log = logging.getLogger(__name__)

LRCLIB_GET_URL = "https://lrclib.net/api/get"
LRCLIB_USER_AGENT = "qobuz-cli (https://github.com/HongYue1/qobuz-cli)"
_LYRICS_TIMEOUT = aiohttp.ClientTimeout(total=12)


def extract_lyrics_query(
    track_meta: dict[str, Any], album_meta: dict[str, Any]
) -> tuple[str, str, str, int | None]:
    """Extracts (artist, title, album, duration) for an LRCLIB lookup."""
    performer = track_meta.get("performer") or {}
    album_artist = album_meta.get("artist") or {}
    artist = performer.get("name") or album_artist.get("name") or ""
    title = track_meta.get("title") or ""
    album = album_meta.get("title") or ""
    duration = track_meta.get("duration")
    if isinstance(duration, float):
        duration = int(duration)
    if not isinstance(duration, int):
        duration = None
    return artist, title, album, duration


class LyricsProvider:
    """Fetches lyrics from LRCLIB and writes them as tags and/or .lrc files."""

    def __init__(self, mode: str = "embed") -> None:
        if mode not in {"embed", "lrc", "both"}:
            mode = "embed"
        self.mode = mode
        self.embed = mode in ("embed", "both")
        self.write_lrc = mode in ("lrc", "both")

    async def process(
        self,
        final_path: str,
        is_mp3: bool,
        track_meta: dict[str, Any],
        album_meta: dict[str, Any],
    ) -> bool:
        """Fetches lyrics for a track and applies them; True on success."""
        artist, title, album, duration = extract_lyrics_query(track_meta, album_meta)
        if not artist or not title:
            return False
        synced, plain = await self._fetch(artist, title, album, duration)
        if not synced and not plain:
            return False
        return await asyncio.to_thread(self._apply, final_path, is_mp3, synced, plain)

    async def _fetch(
        self, artist: str, title: str, album: str, duration: int | None
    ) -> tuple[str | None, str | None]:
        """Queries LRCLIB, returning (synced, plain) lyrics if found."""
        session = await get_connection_pool()
        headers = {"User-Agent": LRCLIB_USER_AGENT}

        precise: dict[str, str] = {"artist_name": artist, "track_name": title}
        if album:
            precise["album_name"] = album
        if duration:
            precise["duration"] = str(duration)

        attempts = [precise]
        if album or duration:
            attempts.append({"artist_name": artist, "track_name": title})

        for params in attempts:
            try:
                async with session.get(
                    LRCLIB_GET_URL,
                    params=params,
                    headers=headers,
                    timeout=_LYRICS_TIMEOUT,
                ) as resp:
                    if resp.status != 200:
                        continue
                    data = await resp.json()
            except (aiohttp.ClientError, TimeoutError, ValueError) as exc:
                log.debug("LRCLIB request failed for '%s': %s", title, exc)
                continue
            synced = data.get("syncedLyrics") or None
            plain = data.get("plainLyrics") or None
            if synced or plain:
                return synced, plain
        return None, None

    def _apply(
        self,
        final_path: str,
        is_mp3: bool,
        synced: str | None,
        plain: str | None,
    ) -> bool:
        """Writes a .lrc/.txt sidecar and/or embeds lyrics into tags."""
        wrote = False
        if self.write_lrc:
            wrote = self._write_sidecar(final_path, synced, plain) or wrote
        if self.embed:
            wrote = self._embed(final_path, is_mp3, synced or plain) or wrote
        return wrote

    def _write_sidecar(
        self, final_path: str, synced: str | None, plain: str | None
    ) -> bool:
        base = Path(final_path)
        if synced:
            base.with_suffix(".lrc").write_text(synced, encoding="utf-8")
            return True
        if plain:
            base.with_suffix(".txt").write_text(plain, encoding="utf-8")
            return True
        return False

    def _embed(self, final_path: str, is_mp3: bool, text: str | None) -> bool:
        if not text:
            return False
        if is_mp3:
            try:
                audio = id3.ID3(final_path)
            except ID3NoHeaderError:
                audio = id3.ID3()
            audio.add(id3.USLT(encoding=3, lang="eng", desc="", text=text))
            audio.save(final_path)
        else:
            audio = FLAC(final_path)
            audio["LYRICS"] = text
            audio.save()
        return True
