"""
Manages loading, validation, and migration of the INI configuration file.
"""

import configparser
import logging
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from qobuz_cli.exceptions import ConfigurationError
from qobuz_cli.models.config import QUALITY_MAP, DownloadConfig

log = logging.getLogger(__name__)

DEFAULT_OUTPUT_TEMPLATE = (
    "{albumartist}/{album} ({year})/"
    "%{?is_multidisc,Disc {media_number}/|}{tracknumber}. {tracktitle}.{ext}"
)

# Reverse map to convert internal API codes back to user-friendly codes for saving
API_TO_USER_QUALITY = {
    v: k for k, v in QUALITY_MAP.items() if isinstance(k, int) and k <= 4
}


class ConfigManager:
    """Handles all operations related to the application's INI config file."""

    def __init__(self, config_file_path: Path):
        self.config_file_path = config_file_path
        self._parser = configparser.ConfigParser()

    def load_config(self, cli_options: dict[str, Any] | None = None) -> DownloadConfig:
        """
        Loads configuration from the INI file, applies CLI overrides, and validates it.

        Args:
            cli_options: A dictionary of options provided via the command line.

        Returns:
            A validated DownloadConfig object.

        Raises:
            ConfigurationError: If the config file is missing, invalid, or validation
            fails.
        """
        if not self.config_file_path.is_file():
            raise ConfigurationError(
                f"Configuration file not found at '{self.config_file_path}'. "
                "Please run 'qobuz-cli init' first."
            )

        try:
            self._parser.read(self.config_file_path)
        except configparser.Error as e:
            raise ConfigurationError(f"Error parsing configuration file: {e}") from e

        if self._migrate_if_needed():
            log.info(
                "[yellow]Configuration file was updated with new default values."
                "[/yellow]"
            )

        config_from_file = self._get_config_as_dict()

        # Override with CLI options
        if cli_options:
            config_from_file.update(cli_options)

        try:
            config_dir = self.config_file_path.parent
            return DownloadConfig(**config_from_file, config_path=str(config_dir))
        except ValidationError as e:
            raise ConfigurationError(f"Configuration validation failed:\n{e}") from e

    def save_new_config(self, settings: dict[str, Any]) -> None:
        """
        Creates and saves a new configuration file.

        Args:
            settings: A dictionary of settings to save.
        """
        config = configparser.ConfigParser()
        config["DEFAULT"] = {}

        # Get all possible keys from the model to create a complete default config
        defaults = DownloadConfig.model_construct(
            output_template=DEFAULT_OUTPUT_TEMPLATE,
            quality=6,
        )
        all_keys = DownloadConfig.get_ini_keys()

        for key in all_keys:
            # Use provided settings first, then fall back to model defaults
            value = settings.get(key, getattr(defaults, key, None))

            if key == "quality":
                # Translate internal API code back to user code for saving
                user_code = API_TO_USER_QUALITY.get(value, 2)
                config["DEFAULT"][key] = str(user_code)
            elif isinstance(value, bool):
                config["DEFAULT"][key] = "true" if value else "false"
            elif isinstance(value, list):
                config["DEFAULT"][key] = ",".join(map(str, value))
            elif key == "output_template" and value:
                # configparser uses % for interpolation, so we must escape it
                config["DEFAULT"][key] = str(value).replace("%", "%%")
            elif value is not None:
                config["DEFAULT"][key] = str(value)

        try:
            self.config_file_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.config_file_path, "w", encoding="utf-8") as configfile:
                config.write(configfile)
        except OSError as e:
            raise ConfigurationError(f"Failed to save configuration file: {e}") from e

    def _get_config_as_dict(self) -> dict[str, Any]:
        """Reads the 'DEFAULT' section of the INI file into a dictionary."""
        section = self._parser["DEFAULT"]
        return {
            "email": section.get("email", ""),
            "password": section.get("password", ""),
            "token": section.get("token", ""),
            "app_id": section.get("app_id", ""),
            "secrets": [
                s.strip() for s in section.get("secrets", "").split(",") if s.strip()
            ],
            "quality": section.getint("quality", 2),
            "max_workers": section.getint("max_workers", 8),
            "output_template": section.get("output_template", DEFAULT_OUTPUT_TEMPLATE),
            "embed_art": section.getboolean("embed_art", False),
            "no_cover": section.getboolean("no_cover", False),
            "og_cover": section.getboolean("og_cover", False),
            "albums_only": section.getboolean("albums_only", False),
            "no_m3u": section.getboolean("no_m3u", False),
            "no_fallback": section.getboolean("no_fallback", False),
            "smart_discography": section.getboolean("smart_discography", False),
            "download_archive": section.getboolean("download_archive", False),
        }

    def _migrate_if_needed(self) -> bool:
        """Adds missing default values to an existing config file."""
        defaults = DownloadConfig.model_construct(
            output_template=DEFAULT_OUTPUT_TEMPLATE,
            quality=6,  # Internal API code
        )
        default_keys = DownloadConfig.get_ini_keys()
        needs_saving = False

        config_section = self._parser["DEFAULT"]

        for key in default_keys:
            if key not in config_section:
                default_value = getattr(defaults, key)

                if key == "quality":
                    # Add missing quality with user-friendly code
                    user_code = API_TO_USER_QUALITY.get(default_value, 2)
                    config_section[key] = str(user_code)
                elif isinstance(default_value, bool):
                    config_section[key] = "false"
                elif isinstance(default_value, list):
                    config_section[key] = ",".join(map(str, default_value))
                elif key == "output_template":
                    config_section[key] = DEFAULT_OUTPUT_TEMPLATE.replace("%", "%%")
                else:
                    config_section[key] = str(default_value)

                needs_saving = True
                log.debug(
                    f"Migrating config: added missing key '{key}' with "
                    f"value '{config_section[key]}'."
                )

        if needs_saving:
            try:
                with open(self.config_file_path, "w", encoding="utf-8") as f:
                    self._parser.write(f)
            except OSError as e:
                log.error(f"Could not save migrated configuration file: {e}")
                return False

        return needs_saving
