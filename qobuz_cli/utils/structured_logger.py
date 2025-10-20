"""
Structured logging system for better log analysis and debugging.
Provides JSON-formatted logs with context and metadata.
"""

import json
import logging
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from rich.console import Console


class StructuredLogger:
    """
    Enhanced logger that outputs both human-readable and machine-parseable logs.

    Usage:
        logger = StructuredLogger("qobuz_cli")
        logger.info("track_downloaded",
                    track_id="12345",
                    size_mb=45.2,
                    duration_s=3.2,
                    quality="FLAC 24/96")
    """

    def __init__(
        self,
        name: str,
        log_dir: Path | None = None,
        enable_json: bool = True,
        enable_console: bool = True,
    ):
        """
        Initialize structured logger.

        Args:
            name: Logger name
            log_dir: Directory for JSON log files (None = disabled)
            enable_json: Enable JSON file logging
            enable_console: Enable console output
        """
        self.name = name
        self.log_dir = log_dir
        self.enable_json = enable_json and log_dir is not None
        self.enable_console = enable_console

        # Standard Python logger for console
        self._logger = logging.getLogger(name)
        self._console = Console() if enable_console else None

        # JSON log file
        self._json_file = None
        if self.enable_json:
            log_dir.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            json_log_path = log_dir / f"qobuz_cli_{timestamp}.jsonl"
            self._json_file = open(json_log_path, "a", encoding="utf-8")  # noqa: SIM115

        # Session context (added to all log entries)
        self._session_context: dict[str, Any] = {
            "session_id": f"{int(time.time())}_{id(self)}",
            "start_time": datetime.now().isoformat(),
        }

    def set_session_context(self, **kwargs) -> None:
        """Set session-level context that appears in all logs."""
        self._session_context.update(kwargs)

    def _format_message(self, event: str, **context) -> str:
        """Format message for console output."""
        parts = [f"[{event}]"]
        for key, value in context.items():
            if key not in ("level", "timestamp"):
                parts.append(f"{key}={value}")
        return " ".join(parts)

    def _write_json(self, level: str, event: str, **context) -> None:
        """Write structured log entry to JSON file."""
        if not self._json_file or self._json_file.closed:
            return

        entry = {
            "timestamp": datetime.now().isoformat(),
            "level": level,
            "event": event,
            **self._session_context,
            **context,
        }

        try:
            self._json_file.write(json.dumps(entry) + "\n")
            self._json_file.flush()
        except Exception as e:
            # Fallback to stderr if JSON logging fails
            print(f"JSON logging failed: {e}", file=sys.stderr)

    def debug(self, event: str, **context) -> None:
        """Log debug event."""
        if self.enable_console:
            self._logger.debug(self._format_message(event, **context))
        if self.enable_json:
            self._write_json("DEBUG", event, **context)

    def info(self, event: str, **context) -> None:
        """Log info event."""
        if self.enable_console:
            self._logger.info(self._format_message(event, **context))
        if self.enable_json:
            self._write_json("INFO", event, **context)

    def warning(self, event: str, **context) -> None:
        """Log warning event."""
        if self.enable_console:
            self._logger.warning(self._format_message(event, **context))
        if self.enable_json:
            self._write_json("WARNING", event, **context)

    def error(self, event: str, **context) -> None:
        """Log error event."""
        if self.enable_console:
            self._logger.error(self._format_message(event, **context))
        if self.enable_json:
            self._write_json("ERROR", event, **context)

    def close(self) -> None:
        """Close JSON log file."""
        if self._json_file and not self._json_file.closed:
            self._json_file.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False


# Pre-configured loggers for common events
class DownloadLogger:
    """Specialized logger for download events."""

    def __init__(self, logger: StructuredLogger):
        self.logger = logger

    def track_started(
        self, track_id: str, title: str, artist: str, album: str, quality: str
    ):
        """Log track download started."""
        self.logger.info(
            "track_download_started",
            track_id=track_id,
            title=title,
            artist=artist,
            album=album,
            quality=quality,
        )

    def track_completed(
        self,
        track_id: str,
        title: str,
        size_bytes: int,
        duration_s: float,
        avg_speed_mbps: float,
    ):
        """Log track download completed."""
        self.logger.info(
            "track_download_completed",
            track_id=track_id,
            title=title,
            size_bytes=size_bytes,
            size_mb=round(size_bytes / (1024 * 1024), 2),
            duration_s=round(duration_s, 2),
            avg_speed_mbps=round(avg_speed_mbps, 2),
        )

    def track_failed(self, track_id: str, title: str, error: str, attempt: int):
        """Log track download failed."""
        self.logger.error(
            "track_download_failed",
            track_id=track_id,
            title=title,
            error=error,
            attempt=attempt,
        )

    def track_skipped(self, track_id: str, title: str, reason: str, reason_code: str):
        """Log track skipped."""
        self.logger.info(
            "track_skipped",
            track_id=track_id,
            title=title,
            reason=reason,
            reason_code=reason_code,
        )


class APILogger:
    """Specialized logger for API events."""

    def __init__(self, logger: StructuredLogger):
        self.logger = logger

    def request_started(self, endpoint: str, params: dict[str, Any]):
        """Log API request started."""
        self.logger.debug(
            "api_request_started",
            endpoint=endpoint,
            params={k: v for k, v in params.items() if k != "user_auth_token"},
        )

    def request_completed(
        self, endpoint: str, status_code: int, duration_ms: float, compressed: bool
    ):
        """Log API request completed."""
        self.logger.debug(
            "api_request_completed",
            endpoint=endpoint,
            status_code=status_code,
            duration_ms=round(duration_ms, 2),
            compressed=compressed,
        )

    def request_failed(
        self, endpoint: str, status_code: int, error: str, duration_ms: float
    ):
        """Log API request failed."""
        self.logger.error(
            "api_request_failed",
            endpoint=endpoint,
            status_code=status_code,
            error=error,
            duration_ms=round(duration_ms, 2),
        )

    def rate_limit_hit(self, endpoint: str, retry_after_s: float | None = None):
        """Log rate limit hit."""
        self.logger.warning(
            "api_rate_limit_hit",
            endpoint=endpoint,
            retry_after_s=retry_after_s,
        )

    def circuit_breaker_opened(self, endpoint: str, failure_count: int):
        """Log circuit breaker opened."""
        self.logger.error(
            "api_circuit_breaker_opened",
            endpoint=endpoint,
            failure_count=failure_count,
        )


class SessionLogger:
    """Specialized logger for session events."""

    def __init__(self, logger: StructuredLogger):
        self.logger = logger

    def session_started(
        self,
        total_urls: int,
        quality: int,
        max_workers: int,
        dry_run: bool = False,
    ):
        """Log session started."""
        self.logger.info(
            "session_started",
            total_urls=total_urls,
            quality=quality,
            max_workers=max_workers,
            dry_run=dry_run,
        )

    def session_completed(
        self,
        duration_s: float,
        tracks_downloaded: int,
        tracks_failed: int,
        tracks_skipped: int,
        total_size_mb: float,
        avg_speed_mbps: float,
    ):
        """Log session completed."""
        self.logger.info(
            "session_completed",
            duration_s=round(duration_s, 2),
            tracks_downloaded=tracks_downloaded,
            tracks_failed=tracks_failed,
            tracks_skipped=tracks_skipped,
            total_size_mb=round(total_size_mb, 2),
            avg_speed_mbps=round(avg_speed_mbps, 2),
        )

    def album_started(self, album_id: str, title: str, artist: str, track_count: int):
        """Log album processing started."""
        self.logger.info(
            "album_started",
            album_id=album_id,
            title=title,
            artist=artist,
            track_count=track_count,
        )

    def album_completed(
        self, album_id: str, title: str, downloaded: int, skipped: int, failed: int
    ):
        """Log album processing completed."""
        self.logger.info(
            "album_completed",
            album_id=album_id,
            title=title,
            tracks_downloaded=downloaded,
            tracks_skipped=skipped,
            tracks_failed=failed,
        )


# Global logger factory
def create_structured_logger(
    log_dir: Path | None = None, enable_json: bool = False
) -> tuple[StructuredLogger, DownloadLogger, APILogger, SessionLogger]:
    """
    Create all structured loggers.

    Returns:
        Tuple of (base_logger, download_logger, api_logger, session_logger)
    """
    base = StructuredLogger("qobuz_cli", log_dir=log_dir, enable_json=enable_json)
    download = DownloadLogger(base)
    api = APILogger(base)
    session = SessionLogger(base)

    return base, download, api, session
