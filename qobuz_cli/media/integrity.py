"""
Provides methods for checking the integrity of downloaded media files.
"""

import logging

from mutagen.flac import FLAC, FLACNoHeaderError
from mutagen.mp3 import MP3, HeaderNotFoundError

log = logging.getLogger(__name__)


class FileIntegrityChecker:
    """A collection of static methods for validating media file integrity."""

    @staticmethod
    def check_flac(filepath: str) -> bool:
        """
        Performs a basic integrity check on a FLAC file.

        Checks if the file can be opened by mutagen and has valid stream info.

        Args:
            filepath: Path to the FLAC file.

        Returns:
            True if the file appears to be a valid FLAC file, False otherwise.
        """
        try:
            audio = FLAC(filepath)
            # A valid FLAC file should have stream info with a positive duration
            if audio.info and audio.info.length > 0:
                return True
            log.warning(
                f"FLAC integrity check failed for '{filepath}': No valid stream info."
            )
            return False
        except FLACNoHeaderError:
            log.warning(
                f"FLAC integrity check failed for '{filepath}': Missing FLAC header."
            )
            return False
        except Exception as e:
            log.debug(f"FLAC check failed for '{filepath}' with unexpected error: {e}")
            return False

    @staticmethod
    def check_mp3(filepath: str) -> bool:
        """
        Performs a basic integrity check on an MP3 file.

        Checks if the file can be opened by mutagen and has valid stream info.

        Args:
            filepath: Path to the MP3 file.

        Returns:
            True if the file appears to be a valid MP3 file, False otherwise.
        """
        try:
            audio = MP3(filepath)
            if audio.info and audio.info.length > 0:
                return True
            log.warning(
                f"MP3 integrity check failed for '{filepath}': No valid stream info."
            )
            return False
        except HeaderNotFoundError:
            log.warning(
                f"MP3 integrity check failed for '{filepath}': Missing MP3 header."
            )
            return False
        except Exception as e:
            log.debug(f"MP3 check failed for '{filepath}' with unexpected error: {e}")
            return False
