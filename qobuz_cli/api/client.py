"""
Enhanced API client with compression for metadata and circuit breaker protection.
"""

import hashlib
import logging
import time
from typing import Any, AsyncGenerator, Dict, List, Optional

import aiohttp

from qobuz_cli.exceptions import (
    AuthenticationError,
    InvalidAppIdError,
    InvalidAppSecretError,
    InvalidQualityError,
)
from qobuz_cli.utils.circuit_breaker import CircuitBreaker, CircuitBreakerError

from .auth import QobuzAuthenticator
from .rate_limiter import AdaptiveRateLimiter

log = logging.getLogger(__name__)


class QobuzAPIClient:
    """
    Optimized async client for the Qobuz JSON API (v0.2).

    Features:
    - Compression for JSON/metadata responses (not audio files)
    - Circuit breaker for API resilience
    - Adaptive rate limiting
    - Connection pooling
    """

    BASE_URL = "https://www.qobuz.com/api.json/0.2/"

    def __init__(self, app_id: str, secrets: List[str], max_workers: int = 8):
        """
        Initializes the API client.

        Args:
            app_id: 9-digit Qobuz application ID from the web player.
            secrets: List of potential app secrets scraped from the web player.
            max_workers: The number of concurrent workers, used to tune the connection pool.
        """
        self.app_id: str = str(app_id)
        self.secrets: List[str] = secrets
        self.max_workers = max_workers

        # State set by the authenticator
        self.app_secret: Optional[str] = None
        self.user_auth_token: Optional[str] = None

        self._session: Optional[aiohttp.ClientSession] = None
        self._rate_limiter = AdaptiveRateLimiter()
        self._authenticator = QobuzAuthenticator(self)

        # Circuit breaker for API resilience
        self._circuit_breaker = CircuitBreaker(
            failure_threshold=5,
            recovery_timeout=60,
            success_threshold=2,
        )

    @property
    def authenticator(self) -> QobuzAuthenticator:
        """Provides access to the authentication helper."""
        return self._authenticator

    async def _initialize_session(self) -> None:
        """Ensures an active aiohttp session is available with compression enabled."""
        if self._session is None or self._session.closed:
            connector = aiohttp.TCPConnector(
                limit=self.max_workers * 2,
                limit_per_host=self.max_workers,
                ttl_dns_cache=300,
                enable_cleanup_closed=True,
            )
            self._session = aiohttp.ClientSession(
                connector=connector,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
                    "X-App-Id": self.app_id,
                    # Enable compression for JSON metadata responses
                    "Accept-Encoding": "gzip, deflate, br",
                },
                timeout=aiohttp.ClientTimeout(total=60, connect=15, sock_read=30),
            )

    async def close(self) -> None:
        """Gracefully closes the aiohttp session."""
        if self._session and not self._session.closed:
            await self._session.close()

    def _prepare_get_file_url_params(
        self, track_id: str, format_id: int, secret_override: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Builds the signed parameter dictionary for the 'track/getFileUrl' endpoint.
        """
        if format_id not in (5, 6, 7, 27):
            raise InvalidQualityError(
                f"Invalid format_id: {format_id}. Must be one of 5, 6, 7, or 27."
            )

        unix_ts = int(time.time())
        secret = secret_override or self.app_secret
        if not secret:
            raise InvalidAppSecretError(
                "App secret has not been configured. Cannot sign request."
            )

        sig_str = f"trackgetFileUrlformat_id{format_id}intentstreamtrack_id{track_id}{unix_ts}{secret}"
        request_sig = hashlib.md5(sig_str.encode("utf-8")).hexdigest()

        return {
            "request_ts": unix_ts,
            "request_sig": request_sig,
            "track_id": track_id,
            "format_id": format_id,
            "intent": "stream",
        }

    async def api_call(self, endpoint: str, **kwargs: Any) -> Dict[str, Any]:
        """
        Makes an authenticated API call with rate limiting, retry logic, and circuit breaker.

        Compression is automatically applied to JSON responses by aiohttp when
        the server sends Content-Encoding header.
        """
        await self._initialize_session()

        # Check circuit breaker before making request
        try:
            async with self._circuit_breaker:
                await self._rate_limiter.acquire()

                params = kwargs.copy()

                if endpoint == "track/getFileUrl":
                    params = self._prepare_get_file_url_params(
                        track_id=params.pop("id"),
                        format_id=params.pop("fmt_id"),
                        secret_override=params.pop("sec", None),
                    )

                if self.user_auth_token:
                    params["user_auth_token"] = self.user_auth_token

                start_time = time.monotonic()

                async with self._session.get(
                    self.BASE_URL + endpoint, params=params
                ) as r:
                    duration_ms = (time.monotonic() - start_time) * 1000

                    # Check if response was compressed (for logging)
                    was_compressed = r.headers.get("Content-Encoding") in (
                        "gzip",
                        "deflate",
                        "br",
                    )
                    if was_compressed:
                        log.debug(
                            f"API response for {endpoint} was compressed ({r.headers.get('Content-Encoding')})"
                        )

                    if r.status == 429:
                        await self._rate_limiter.on_429()
                        r.raise_for_status()

                    if endpoint == "user/login":
                        if r.status == 401:
                            raise AuthenticationError("Invalid email or password.")
                        if r.status == 400 and "Invalid application" in await r.text():
                            raise InvalidAppIdError("The provided App ID is invalid.")

                    if endpoint == "track/getFileUrl" and r.status == 400:
                        raise InvalidAppSecretError(
                            "The app secret is invalid or has expired."
                        )

                    r.raise_for_status()
                    return await r.json()

        except CircuitBreakerError as e:
            log.error(f"[red]Circuit breaker is open for API calls: {e}[/red]")
            raise
        except Exception as e:
            log.debug(f"API call to {endpoint} failed: {e}")
            raise

    async def _yield_paginated(
        self, endpoint: str, item_key: str, **kwargs: Any
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        Generator for handling paginated API endpoints.
        """
        offset = 0
        limit = 200
        total_items = 0

        while True:
            response = await self.api_call(
                endpoint, offset=offset, limit=limit, **kwargs
            )

            if offset == 0:
                total_items = response.get(f"{item_key}_count", 0)

            items_in_response = len(response.get(item_key, {}).get("items", []))
            if not items_in_response:
                break

            yield response

            offset += items_in_response
            if offset >= total_items:
                break

    # Public API Methods
    async def fetch_album_metadata(self, album_id: str) -> Dict[str, Any]:
        return await self.api_call("album/get", album_id=album_id)

    async def fetch_track_metadata(self, track_id: str) -> Dict[str, Any]:
        return await self.api_call("track/get", track_id=track_id)

    async def fetch_track_url(self, track_id: str, format_id: int) -> Dict[str, Any]:
        return await self.api_call("track/getFileUrl", id=track_id, fmt_id=format_id)

    def fetch_artist_discography(
        self, artist_id: str
    ) -> AsyncGenerator[Dict[str, Any], None]:
        return self._yield_paginated(
            "artist/get", item_key="albums", artist_id=artist_id, extra="albums"
        )

    def fetch_playlist_tracks(
        self, playlist_id: str
    ) -> AsyncGenerator[Dict[str, Any], None]:
        return self._yield_paginated(
            "playlist/get", item_key="tracks", playlist_id=playlist_id, extra="tracks"
        )

    def fetch_label_discography(
        self, label_id: str
    ) -> AsyncGenerator[Dict[str, Any], None]:
        return self._yield_paginated(
            "label/get", item_key="albums", label_id=label_id, extra="albums"
        )

    async def search_tracks(self, query: str, limit: int = 50) -> Dict[str, Any]:
        return await self.api_call("track/search", query=query, limit=limit)
