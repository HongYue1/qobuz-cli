"""
JSON Schema validation for configuration files.
Allows external tools to validate configs and provides better error messages.
"""

import json
from pathlib import Path
from typing import Any

# JSON Schema for qobuz-cli configuration
CONFIG_SCHEMA = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "title": "Qobuz-CLI Configuration",
    "description": "Configuration schema for qobuz-cli downloader",
    "type": "object",
    "properties": {
        # Authentication
        "email": {
            "type": "string",
            "format": "email",
            "description": "Qobuz account email",
        },
        "password": {
            "type": "string",
            "minLength": 32,
            "maxLength": 32,
            "description": "MD5 hash of password",
        },
        "token": {
            "type": "string",
            "description": "User authentication token",
        },
        "app_id": {
            "type": "string",
            "pattern": "^\\d{9}$",
            "description": "9-digit Qobuz application ID",
        },
        "secrets": {
            "type": "array",
            "items": {"type": "string", "minLength": 1},
            "minItems": 1,
            "description": "List of app secrets",
        },
        # Download settings
        "quality": {
            "type": "integer",
            "enum": [5, 6, 7, 27],
            "description": "Audio quality (5=MP3 320, 6=CD, 7=Hi-Res, 27=Hi-Res+)",
        },
        "max_workers": {
            "type": "integer",
            "minimum": 1,
            "maximum": 32,
            "description": "Maximum concurrent downloads",
        },
        "output_template": {
            "type": "string",
            "minLength": 1,
            "description": "Output path template with placeholders",
        },
        # Boolean options
        "embed_art": {
            "type": "boolean",
            "description": "Embed cover art in audio files",
        },
        "no_cover": {
            "type": "boolean",
            "description": "Skip downloading cover art files",
        },
        "og_cover": {
            "type": "boolean",
            "description": "Download original quality cover art",
        },
        "albums_only": {
            "type": "boolean",
            "description": "Skip non-album releases",
        },
        "no_m3u": {
            "type": "boolean",
            "description": "Skip M3U playlist generation",
        },
        "no_fallback": {
            "type": "boolean",
            "description": "Disable quality fallback",
        },
        "smart_discography": {
            "type": "boolean",
            "description": "Filter duplicate albums in discography",
        },
        "download_archive": {
            "type": "boolean",
            "description": "Track downloaded files to avoid redownloading",
        },
    },
    "required": ["app_id", "secrets"],
    "anyOf": [
        {"required": ["token"]},
        {"required": ["email", "password"]},
    ],
    "additionalProperties": False,
}


def validate_config_schema(config_dict: dict[str, Any]) -> tuple[bool, list[str]]:
    """
    Validate configuration against JSON schema.

    Args:
        config_dict: Configuration dictionary

    Returns:
        Tuple of (is_valid, error_messages)
    """
    try:
        from jsonschema import Draft7Validator

        validator = Draft7Validator(CONFIG_SCHEMA)
        errors = sorted(validator.iter_errors(config_dict), key=lambda e: e.path)

        if not errors:
            return True, []

        error_messages = []
        for error in errors:
            path = ".".join(str(p) for p in error.path) if error.path else "root"
            error_messages.append(f"{path}: {error.message}")

        return False, error_messages

    except ImportError:
        return True, ["Warning: jsonschema not installed, skipping schema validation"]


def export_schema(output_path: Path) -> None:
    """
    Export JSON schema to file for external validation tools.

    Args:
        output_path: Path to save schema file
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(CONFIG_SCHEMA, f, indent=2)


def validate_output_template(template: str) -> tuple[bool, str | None]:
    """
    Validate output template has required placeholders.

    Args:
        template: Output path template

    Returns:
        Tuple of (is_valid, error_message)
    """
    if not template:
        return False, "Template cannot be empty"

    if ".." in template or template.startswith(("/", "\\")):
        return False, "Template cannot contain '..' or absolute paths"

    required_placeholders = ["{tracknumber}", "{tracktitle}"]
    has_required = any(ph in template for ph in required_placeholders)

    if not has_required:
        return (
            False,
            "Template must contain at least one "
            f"of: {', '.join(required_placeholders)}",
        )

    # Check for invalid characters
    invalid_chars = set('<>:"|?*')
    template_chars = set(template)
    if overlap := invalid_chars & template_chars:
        return False, f"Template contains invalid characters: {', '.join(overlap)}"

    return True, None


def validate_quality_conflicts(config: dict[str, Any]) -> tuple[bool, list[str]]:
    """
    Check for conflicting quality/cover settings.

    Args:
        config: Configuration dictionary

    Returns:
        Tuple of (is_valid, error_messages)
    """
    errors = []

    # Check cover art conflicts
    if config.get("no_cover") and config.get("embed_art"):
        errors.append("Cannot use no_cover=true and embed_art=true simultaneously")

    if config.get("no_cover") and config.get("og_cover"):
        errors.append("Cannot use no_cover=true and og_cover=true simultaneously")

    # Check quality fallback
    quality = config.get("quality", 6)
    no_fallback = config.get("no_fallback", False)

    if no_fallback and quality in [7, 27]:
        errors.append(
            "Warning: no_fallback=true with Hi-Res quality "
            "may cause many skipped tracks"
        )

    return len(errors) == 0, errors
