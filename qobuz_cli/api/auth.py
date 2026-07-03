"""
Handles authentication with the Qobuz API, including credential login
and app secret validation.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

import aiohttp

from qobuz_cli.exceptions import (
    AuthenticationError,
    IneligibleAccountError,
    InvalidAppSecretError,
)

if TYPE_CHECKING:
    from .client import QobuzAPIClient

log = logging.getLogger(__name__)


class QobuzAuthenticator:
    """
    Manages the authentication flow for the Qobuz API client.
    """

    def __init__(self, api_client: QobuzAPIClient):
        """
        Initializes the authenticator.

        Args:
            api_client: A reference to the main QobuzAPIClient instance.
        """
        self._api_client = api_client
        self._secrets_tested = False

    async def authenticate_with_token(self, token: str) -> dict[str, Any]:
        """
        Authenticates the client using a pre-existing user token.

        Args:
            token: The user authentication token.

        Returns:
            The user information dictionary from the API.
        """
        log.info("Authenticating with token...")
        self._api_client.user_auth_token = token
        await self.configure_authentication()

        try:
            user_info = await self._api_client.api_call("user/get")
            log.info(
                "Successfully authenticated as: "
                f"{user_info.get('email', 'Unknown User')}"
            )

            if not user_info.get("credential", {}).get("parameters"):
                raise IneligibleAccountError(
                    "This account is not eligible for streaming."
                )
            return user_info
        except aiohttp.ClientResponseError as e:
            if e.status == 401:
                raise AuthenticationError(
                    "The provided token is invalid or has expired."
                ) from e
            raise

    async def authenticate_with_credentials(
        self, email: str, password_md5: str
    ) -> dict[str, Any]:
        """
        Authenticates using an email and an MD5-hashed password.

        Args:
            email: The user's email address.
            password_md5: The user's password, hashed with MD5.

        Returns:
            The user information dictionary from the API.
        """
        log.info(f"Authenticating as: {email}")
        await self.configure_authentication()

        login_payload = {
            "email": email,
            "password": password_md5,
            "app_id": self._api_client.app_id,
        }

        user_info = await self._api_client.api_call("user/login", **login_payload)

        if not user_info.get("user", {}).get("credential", {}).get("parameters"):
            raise IneligibleAccountError("This account is not eligible for streaming.")

        self._api_client.user_auth_token = user_info["user_auth_token"]
        return user_info

    async def configure_authentication(self) -> None:
        """
        Finds and sets a valid app secret from the provided list.

        Tests each secret against a known valid endpoint until one succeeds.
        This is a crucial step before making authenticated API calls.
        """
        if self._api_client.app_secret:
            return

        log.debug(f"Testing {len(self._api_client.secrets)} potential app secrets...")

        # Only test non-empty secrets, and keep the tested list aligned with the
        # results so a falsy secret can never desynchronize the zip below.
        valid_candidates = [s for s in self._api_client.secrets if s]
        results = await asyncio.gather(
            *(self._test_secret(secret) for secret in valid_candidates)
        )

        for secret, is_valid in zip(valid_candidates, results, strict=True):
            if is_valid:
                self._api_client.app_secret = secret
                log.debug(f"Valid secret found: {secret[:8]}...")
                return

        raise InvalidAppSecretError(
            "No valid app secrets found."
            " Please run 'qobuz-cli init' to fetch new secrets."
        )

    async def _test_secret(self, secret: str) -> bool:
        """
        Tests if a single app secret is valid.

        The secret is used to sign the ``track/getFileUrl`` request.  A 400
        response means Qobuz explicitly rejected the signature, so the secret
        is bad.  Any *other* HTTP error (404 track gone, 403 subscription
        restriction, etc.) means the signed request was accepted by the server
        — the secret is valid, the track or subscription is the problem.

        Args:
            secret: The app secret to test.

        Returns:
            True if the secret is valid, False otherwise.
        """
        try:
            await self._api_client.api_call(
                "track/getFileUrl", id=5966783, fmt_id=5, sec=secret
            )
            return True
        except InvalidAppSecretError:
            # HTTP 400: Qobuz explicitly rejected the signature — bad secret.
            return False
        except aiohttp.ClientResponseError:
            # Non-400 HTTP error (e.g. 404 track removed, 403 subscription).
            # The signed request was accepted; the secret itself is valid.
            log.debug(
                "Secret test received a non-400 HTTP error; "
                "signature was accepted — treating secret as valid."
            )
            return True
        except aiohttp.ClientError:
            # Network-level failure — cannot determine validity.
            log.debug("Secret test failed due to a network error.")
            return False
