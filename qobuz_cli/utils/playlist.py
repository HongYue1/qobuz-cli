"""
Utility for generating M3U playlist files.
"""

import logging
import re
from pathlib import Path

from mutagen import File as MutagenFile
from mutagen import MutagenError

log = logging.getLogger(__name__)


def generate_m3u(playlist_directory: Path) -> bool:
    """
    Generates an M3U playlist file for all audio tracks in a given directory.
    """
    playlist_name = f"{playlist_directory.name}.m3u"
    playlist_path = playlist_directory / playlist_name

    audio_files = sorted(
        [p for p in playlist_directory.rglob("*") if p.suffix in (".mp3", ".flac")],
        key=lambda p: (
            p.parent,
            int(re.match(r"(\d+)", p.name).group(1))
            if re.match(r"(\d+)", p.name)
            else 999,
        ),
    )

    if not audio_files:
        log.debug(f"No audio files found in '{playlist_directory}' to create playlist.")
        return False

    content = ["#EXTM3U"]
    for audio_path in audio_files:
        try:
            audio = MutagenFile(audio_path, easy=True)
            length = int(audio.info.length) if audio and audio.info else -1
            artist = audio.get("artist", ["Unknown Artist"])[0]
            title = audio.get("title", [audio_path.stem])[0]
            content.append(f"#EXTINF:{length},{artist} - {title}")
            content.append(str(audio_path.relative_to(playlist_directory).as_posix()))
        except MutagenError:
            content.append(f"#EXTINF:-1,{audio_path.stem}")
            content.append(str(audio_path.relative_to(playlist_directory).as_posix()))

    try:
        with open(playlist_path, "w", encoding="utf-8") as f:
            f.write("\n".join(content))
        log.info(f"Generated playlist: '{playlist_path}'")
        return True
    except IOError as e:
        log.error(f"Failed to write playlist file: {e}")
        return False
