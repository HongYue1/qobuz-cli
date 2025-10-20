"""
Handles parsing of Qobuz metadata and writing it as tags to media files.
"""

import logging
import os
import re
from typing import Any, Dict, List, Optional

import mutagen.id3 as id3
from mutagen.flac import FLAC, Picture
from mutagen.id3 import ID3NoHeaderError

from qobuz_cli.utils.formatting import get_track_title

log = logging.getLogger(__name__)

# --- Constants ---
COPYRIGHT, PHON_COPYRIGHT = "\u00a9", "\u2117"
FLAC_MAX_BLOCKSIZE = 16777215  # ~16.7MB, max size for a FLAC metadata block


class PerformersParser:
    """
    Parses the complex 'performers' string and track title from the Qobuz API
    to extract artists by role.
    """

    ROLE_MAPPING = {
        "mainartist": "Main",
        "performer": "Main",
        "featuredartist": "Featured",
        "composer": "Composer",
        "composerlyricist": "Composer",
        "lyricist": "Composer",
        "writer": "Composer",
        "author": "Composer",
        "producer": "Producer",
        "co-producer": "Producer",
        "mixer": "Engineer",
        "musicpublisher": "Publisher",
    }

    def __init__(
        self, performers_string: Optional[str], track_title: Optional[str] = None
    ):
        self._performers: Dict[str, List[str]] = {}
        if performers_string:
            self._parse_string(performers_string)
        if track_title:
            self._parse_title(track_title)

    def _parse_string(self, performers_string: str):
        person_to_roles: Dict[str, List[str]] = {}
        for person_chunk in performers_string.split(" - "):
            parts = [p.strip() for p in person_chunk.split(",")]
            if len(parts) < 2:
                continue
            name, roles = parts[0], parts[1:]
            if name:
                person_to_roles[name] = roles

        for name, roles in person_to_roles.items():
            for role_raw in roles:
                role_key = role_raw.replace(" ", "").lower()
                if standard_role := self.ROLE_MAPPING.get(role_key):
                    if name not in self._performers.setdefault(standard_role, []):
                        self._performers[standard_role].append(name)

    def _parse_title(self, title: str):
        """Extracts featured artists from the title and adds them to the parser."""
        match = re.search(r"\((?:feat|ft|with)\.?\s+(.*?)\)", title, re.IGNORECASE)
        if not match:
            return

        artists_str = match.group(1)
        featured_artists = [
            artist.strip()
            for artist in re.split(r"\s*[,&]\s*|\s+and\s+", artists_str)
            if artist.strip()
        ]

        current_featured = self._performers.setdefault("Featured", [])
        for artist in featured_artists:
            if artist not in current_featured:
                current_featured.append(artist)

    def get_performers_by_role(self, role: str) -> List[str]:
        return self._performers.get(role, [])

    def get_primary_artists(self) -> List[str]:
        return self.get_performers_by_role("Main")


class Tagger:
    """Writes metadata tags to MP3 and FLAC files."""

    def __init__(self, embed_art: bool):
        self.embed_art = embed_art

    def tag_file(
        self,
        temp_file_path: str,
        final_file_path: str,
        track_meta: Dict[str, Any],
        album_meta: Dict[str, Any],
        is_mp3: bool,
    ) -> bool:
        try:
            if is_mp3:
                self._tag_mp3(temp_file_path, final_file_path, track_meta, album_meta)
            else:
                self._tag_flac(temp_file_path, final_file_path, track_meta, album_meta)

            os.rename(temp_file_path, final_file_path)
            return True
        except Exception as e:
            log.error(
                f"Failed to tag file '{os.path.basename(final_file_path)}': {e}",
                exc_info=log.getEffectiveLevel() == logging.DEBUG,
            )
            return False

    def _get_common_tags(
        self, track_meta: Dict[str, Any], album_meta: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Gathers and formats tags common to both MP3 and FLAC."""
        parser = PerformersParser(track_meta.get("performers"), track_meta.get("title"))

        main_artists = parser.get_primary_artists() or [
            track_meta.get("performer", {}).get("name", "Unknown Artist")
        ]
        featured_artists = parser.get_performers_by_role("Featured")
        all_artists = list(dict.fromkeys(main_artists + featured_artists))

        genres = []
        if genre_list := album_meta.get("genres_list"):
            for genre_str in genre_list:
                parts = re.split(r"[\u2192/]", genre_str)
                genres.extend(p.strip() for p in parts if p.strip())

        copyright_str = track_meta.get("copyright") or album_meta.get("copyright")

        return {
            "title": get_track_title(track_meta),
            "album": album_meta.get("title", "Unknown Album"),
            "artist": all_artists,
            "albumartist": album_meta.get("artist", {}).get("name", "Unknown Artist"),
            "tracknumber": str(track_meta.get("track_number", 0)),
            "tracktotal": str(album_meta.get("tracks_count", 0)),
            "discnumber": str(track_meta.get("media_number", 1)),
            "disctotal": str(album_meta.get("media_count", 1)),
            "date": album_meta.get("release_date_original", ""),
            "isrc": track_meta.get("isrc"),
            "genre": list(dict.fromkeys(g.capitalize() for g in genres if g)),
            "label": album_meta.get("label", {}).get("name"),
            "barcode": album_meta.get("upc"),
            "copyright": copyright_str.replace("(P)", PHON_COPYRIGHT).replace(
                "(C)", COPYRIGHT
            )
            if copyright_str
            else None,
            "composer": parser.get_performers_by_role("Composer")
            or [track_meta.get("composer", {}).get("name")],
            "producer": parser.get_performers_by_role("Producer"),
        }

    def _tag_flac(
        self, temp_path: str, final_path: str, track_meta: Dict, album_meta: Dict
    ):
        audio = FLAC(temp_path)
        tags = self._get_common_tags(track_meta, album_meta)

        for key, value in tags.items():
            if value:
                processed_value = (
                    [str(v) for v in value if v]
                    if isinstance(value, list)
                    else [str(value)]
                )
                if processed_value:
                    audio[key.upper()] = processed_value

        if self.embed_art:
            self._embed_flac_cover(os.path.dirname(final_path), audio)

        audio.save()

    def _tag_mp3(
        self, temp_path: str, final_path: str, track_meta: Dict, album_meta: Dict
    ):
        try:
            audio = id3.ID3(temp_path)
        except ID3NoHeaderError:
            audio = id3.ID3()

        tags = self._get_common_tags(track_meta, album_meta)

        audio.add(id3.TIT2(encoding=3, text=tags["title"]))
        audio.add(id3.TALB(encoding=3, text=tags["album"]))
        audio.add(id3.TPE1(encoding=3, text=tags["artist"]))
        audio.add(id3.TPE2(encoding=3, text=tags["albumartist"]))
        audio.add(
            id3.TRCK(encoding=3, text=f"{tags['tracknumber']}/{tags['tracktotal']}")
        )
        audio.add(
            id3.TPOS(encoding=3, text=f"{tags['discnumber']}/{tags['disctotal']}")
        )
        if tags["date"]:
            audio.add(id3.TDRC(encoding=3, text=tags["date"]))
        if tags["genre"]:
            audio.add(id3.TCON(encoding=3, text="/".join(tags["genre"])))
        if tags["isrc"]:
            audio.add(id3.TSRC(encoding=3, text=tags["isrc"]))
        if tags["label"]:
            audio.add(id3.TPUB(encoding=3, text=tags["label"]))
        if tags["copyright"]:
            audio.add(id3.TCOP(encoding=3, text=tags["copyright"]))
        if composers := [c for c in tags.get("composer", []) if c]:
            audio.add(id3.TCOM(encoding=3, text=composers))
        if producers := [p for p in tags.get("producer", []) if p]:
            audio.add(id3.TXXX(encoding=3, desc="PRODUCER", text=producers))
        if tags["barcode"]:
            audio.add(id3.TXXX(encoding=3, desc="BARCODE", text=tags["barcode"]))

        if self.embed_art:
            self._embed_mp3_cover(os.path.dirname(final_path), audio)

        audio.save(filename=temp_path, v2_version=3)

    def _embed_flac_cover(self, directory: str, audio: FLAC):
        cover_path = os.path.join(directory, "cover.jpg")
        if not os.path.isfile(cover_path):
            return
        if os.path.getsize(cover_path) > FLAC_MAX_BLOCKSIZE:
            log.warning(
                "Cover art is too large to embed in FLAC. Try disabling --og-cover."
            )
            return

        pic = Picture()
        pic.type = 3
        pic.mime = "image/jpeg"
        with open(cover_path, "rb") as f:
            pic.data = f.read()

        audio.clear_pictures()
        audio.add_picture(pic)

    def _embed_mp3_cover(self, directory: str, audio: id3.ID3):
        cover_path = os.path.join(directory, "cover.jpg")
        if not os.path.isfile(cover_path):
            return

        with open(cover_path, "rb") as f:
            if "APIC:" in audio:
                del audio["APIC:"]
            audio.add(
                id3.APIC(
                    encoding=3, mime="image/jpeg", type=3, desc="Cover", data=f.read()
                )
            )
