"""
Media Processing Layer.

This package is responsible for all media file operations, including
downloading, metadata tagging, and integrity validation.
"""

from .downloader import Downloader
from .integrity import FileIntegrityChecker
from .lyrics import LyricsProvider
from .tagger import Tagger

__all__ = ["Downloader", "FileIntegrityChecker", "LyricsProvider", "Tagger"]
