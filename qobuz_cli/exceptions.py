"""
Defines custom exceptions for the application to allow for more specific
error handling and user feedback.
"""


class QobuzCliError(Exception):
    """Base exception for all application-specific errors."""

    pass


class AuthenticationError(QobuzCliError):
    """Raised when user login fails due to invalid credentials or token."""

    pass


class IneligibleAccountError(QobuzCliError):
    """Raised when the user's account is not eligible for streaming."""

    pass


class InvalidAppIdError(QobuzCliError):
    """Raised when the provided App ID is rejected by the Qobuz API."""

    pass


class InvalidAppSecretError(QobuzCliError):
    """Raised when the derived app secrets are invalid or none can be found."""

    pass


class InvalidQualityError(QobuzCliError):
    """Raised when an invalid quality ID is requested."""

    pass


class NotStreamableError(QobuzCliError):
    """Raised when attempting to download an item that is not available for streaming."""

    pass


class ConfigurationError(QobuzCliError):
    """Raised for issues related to configuration loading or validation."""

    pass


class FileIntegrityError(QobuzCliError):
    """Raised when a downloaded file fails a post-download integrity check."""

    pass
