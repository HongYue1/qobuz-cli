"""
Fetches and parses the Qobuz web player's JavaScript bundle to extract
the app_id and app_secrets required for API authentication.
"""

import asyncio
import base64
import logging
import re
from collections import OrderedDict

import aiohttp

from qobuz_cli.exceptions import InvalidAppSecretError

log = logging.getLogger(__name__)

# Pre-compiled regex for performance
_BASE_URL = "https://play.qobuz.com"
_BUNDLE_URL_REGEX = re.compile(
    r'<script src="(/resources/[\d.-]+[a-z]\d{3}/bundle\.js)"></script>'
)
_APP_ID_REGEX = re.compile(r'production:{api:{appId:"(?P<app_id>\d{9})"')
_SEED_TIMEZONE_REGEX = re.compile(
    r'[a-z]\.initialSeed\("(?P<seed>[\w=]+)",window\.utimezone\.(?P<timezone>[a-z]+)\)'
)
_INFO_EXTRAS_TEMPLATE = (
    r'name:"\w+/(?P<timezone>{timezones})",'
    r'info:"(?P<info>[\w=]+)",extras:"(?P<extras>[\w=]+)"'
)


class BundleFetcher:
    """
    Fetches the main JavaScript bundle from the Qobuz web player and
    parses it to extract critical authentication parameters.
    """

    def __init__(self, bundle_content: str):
        self._bundle_content = bundle_content

    @classmethod
    async def fetch(cls, max_retries: int = 3) -> "BundleFetcher":
        """
        Fetches the bundle from the Qobuz website with retry logic.
        """
        timeout = aiohttp.ClientTimeout(total=45, connect=15)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            for attempt in range(1, max_retries + 1):
                try:
                    log.debug(
                        f"Attempt {attempt}/{max_retries} to fetch Qobuz bundle..."
                    )

                    login_page_url = f"{_BASE_URL}/login"
                    async with session.get(login_page_url) as response:
                        response.raise_for_status()
                        page_html = await response.text()

                    bundle_match = _BUNDLE_URL_REGEX.search(page_html)
                    if not bundle_match:
                        raise RuntimeError(
                            "Could not find bundle URL on the Qobuz login page."
                        )

                    bundle_url = _BASE_URL + bundle_match.group(1)
                    log.debug(f"Found bundle URL: {bundle_url}")

                    async with session.get(bundle_url) as response:
                        response.raise_for_status()
                        bundle_text = await response.text()

                    if len(bundle_text) < 10000:
                        raise ValueError("Fetched bundle content seems too small.")

                    log.debug(
                        f"Successfully fetched bundle ({len(bundle_text)} bytes)."
                    )
                    return cls(bundle_text)

                except (aiohttp.ClientError, ValueError, RuntimeError) as e:
                    log.warning(f"Bundle fetch attempt {attempt} failed: {e}")
                    if attempt == max_retries:
                        raise RuntimeError(
                            f"Failed to fetch bundle after {max_retries} attempts."
                        ) from e
                    await asyncio.sleep(2**attempt)

        raise RuntimeError("Bundle fetching failed unexpectedly.")

    def extract_app_id(self) -> str:
        """Extracts the 9-digit application ID from the bundle content."""
        match = _APP_ID_REGEX.search(self._bundle_content)
        if not match:
            raise RuntimeError("Could not find app_id in the JavaScript bundle.")

        app_id = match.group("app_id")
        log.debug(f"Extracted App ID: {app_id}")
        return app_id

    def extract_secrets(self) -> dict[str, str]:
        """Extracts and decodes the API secrets from the bundle."""
        log.debug("Extracting secrets from bundle...")

        seeds_by_timezone = OrderedDict()
        for match in _SEED_TIMEZONE_REGEX.finditer(self._bundle_content):
            seed, timezone = match.group("seed", "timezone")
            seeds_by_timezone[timezone] = [seed]

        if not seeds_by_timezone:
            raise InvalidAppSecretError(
                "Could not find any initial seeds in the bundle."
            )

        if len(seeds_by_timezone) > 1:
            first_key = next(iter(seeds_by_timezone))
            seeds_by_timezone.move_to_end(first_key)

        timezones_regex_part = "|".join(tz.capitalize() for tz in seeds_by_timezone)
        info_extras_regex = re.compile(
            _INFO_EXTRAS_TEMPLATE.format(timezones=timezones_regex_part)
        )

        for match in info_extras_regex.finditer(self._bundle_content):
            timezone, info, extras = match.group("timezone", "info", "extras")
            tz_lower = timezone.lower()
            if tz_lower in seeds_by_timezone:
                seeds_by_timezone[tz_lower].extend([info, extras])

        decoded_secrets = OrderedDict()
        for tz, parts in seeds_by_timezone.items():
            if len(parts) != 3:
                log.warning(f"Incomplete secret parts for timezone '{tz}', skipping.")
                continue

            try:
                full_secret_encoded = "".join(parts)
                # The last 44 characters are a salt/checksum and must be removed
                # before Base64 decoding the actual secret.
                trimmed_secret = full_secret_encoded[:-44]
                decoded = base64.standard_b64decode(trimmed_secret).decode("utf-8")
                decoded_secrets[tz] = decoded
                log.debug(f"Decoded secret for '{tz}': {decoded[:8]}...")
            except (ValueError, TypeError) as e:
                raise InvalidAppSecretError(
                    f"Failed to decode secret for timezone '{tz}': {e}"
                ) from e

        if not decoded_secrets:
            raise InvalidAppSecretError(
                "No secrets could be successfully decoded from the bundle."
            )

        return decoded_secrets
