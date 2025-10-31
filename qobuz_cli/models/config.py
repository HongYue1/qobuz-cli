"""
Pydantic model for application configuration.
Provides robust validation for all settings.
"""

from pydantic import BaseModel, Field, field_validator, model_validator

# Maps user-friendly codes to API codes and provides metadata
QUALITY_MAP = {
    # User code -> API code
    1: 5,
    2: 6,
    3: 7,
    4: 27,
    # API code -> Metadata (for internal use)
    5: {
        "name": "MP3 320kbps",
        "short": "MP3 320",
        "ext": "mp3",
        "color": "yellow",
        "user_code": 1,
    },
    6: {
        "name": "CD Lossless (16/44.1)",
        "short": "16/44.1",
        "ext": "flac",
        "color": "green",
        "user_code": 2,
    },
    7: {
        "name": "Hi-Res (up to 24/96)",
        "short": "24/96",
        "ext": "flac",
        "color": "cyan",
        "user_code": 3,
    },
    27: {
        "name": "Hi-Res+ (up to 24/192)",
        "short": "24/192",
        "ext": "flac",
        "color": "magenta",
        "user_code": 4,
    },
}


def get_quality_info(quality_id: int) -> dict[str, str]:
    """Gets all information for a given quality ID from the central map."""
    return QUALITY_MAP.get(
        quality_id,
        {
            "name": "Unknown",
            "short": "Unknown",
            "ext": "flac",
            "color": "white",
            "user_code": 0,
        },
    )


class DownloadConfig(BaseModel):
    """A validated configuration model for the application."""

    # Authentication & API
    email: str = ""
    password: str = ""  # This will be the MD5 hash
    token: str = ""
    app_id: str = ""
    secrets: list[str] = Field(default_factory=list)

    # Download Settings
    quality: int = 6
    max_workers: int = 8
    output_template: str
    no_fallback: bool = False
    dry_run: bool = False
    download_archive: bool = False

    # Tagging and File Options
    embed_art: bool = False
    no_cover: bool = False
    og_cover: bool = False
    no_m3u: bool = False

    # Filtering Options
    albums_only: bool = False
    smart_discography: bool = False

    # Internal fields not loaded from INI file
    config_path: str = Field(..., repr=False)
    source_urls: list[str] = Field(default_factory=list, repr=False)

    class Config:
        """Pydantic model configuration."""

        validate_assignment = True
        str_strip_whitespace = True

    @field_validator("quality")
    @classmethod
    def validate_quality(cls, v: int) -> int:
        """
        Ensures quality is a valid user code (1-4) or API code and translates it
        to the internal API code.
        """
        # If it's a user code (1-4), map it to the API code
        if v in (1, 2, 3, 4):
            return QUALITY_MAP[v]

        # If it's a direct API code, ensure it's valid
        if v not in (5, 6, 7, 27):
            raise ValueError(
                "Quality must be one of 1 (MP3), 2 (CD), 3 (Hi-Res), 4 (Hi-Res+)."
            )
        return v

    @field_validator("max_workers")
    @classmethod
    def validate_workers(cls, v: int) -> int:
        """Ensures a reasonable number of workers."""
        if v < 1 or v > 32:
            raise ValueError("Max workers must be between 1 and 32.")
        return v

    @field_validator("output_template")
    @classmethod
    def validate_template(cls, v: str) -> str:
        """Validates the output path template."""
        if not v:
            raise ValueError("Output template cannot be empty.")
        if ".." in v or v.startswith(("/", "\\")):
            raise ValueError(
                "Output template cannot contain relative '..' or absolute paths."
            )
        if "{tracknumber}" not in v and "{tracktitle}" not in v:
            raise ValueError(
                "Output template must contain at least {tracknumber} or {tracktitle}."
            )
        return v

    @model_validator(mode="after")
    def validate_auth_and_api_config(self) -> "DownloadConfig":
        """Validates that authentication and API settings are sufficient."""
        has_token = bool(self.token and self.token.strip())
        has_email_pass = bool(
            self.email
            and self.email.strip()
            and self.password
            and self.password.strip()
        )

        if not has_token and not has_email_pass:
            raise ValueError(
                "Authentication not configured. Provide either a token or "
                "email/password."
            )

        if not self.app_id or not self.app_id.strip() or not self.secrets:
            raise ValueError(
                "API settings are incomplete. 'app_id' and 'secrets' are required."
            )

        if not self.app_id.isdigit() or len(self.app_id) != 9:
            raise ValueError(f"App ID must be 9 digits, but got: {self.app_id}")

        return self

    @model_validator(mode="after")
    def validate_option_conflicts(self) -> "DownloadConfig":
        """Checks for conflicting download options."""
        if self.no_cover and self.embed_art:
            raise ValueError("Cannot use --no-cover and --embed-art simultaneously.")
        if self.no_cover and self.og_cover:
            raise ValueError("Cannot use --no-cover and --og-cover simultaneously.")
        return self

    @classmethod
    def get_ini_keys(cls) -> set[str]:
        """Returns a set of all keys that are expected in the INI file."""
        internal_fields = {"config_path", "source_urls"}
        return {key for key in cls.model_fields if key not in internal_fields}
