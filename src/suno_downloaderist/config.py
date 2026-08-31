"""Configuration management for Suno Song Downloaderist."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator

from suno_downloaderist.utils import get_config_dir, get_default_output_dir

logger = logging.getLogger(__name__)

CONFIG_FILENAME = "config.json"


class AppConfig(BaseModel):
    """Application configuration with sensible defaults.

    All settings can be overridden via config file, CLI flags, or environment variables.
    """

    # Output settings
    output_dir: Path = Field(
        default_factory=get_default_output_dir,
        description="Directory where downloaded songs will be saved.",
    )

    # Format settings
    download_mp3: bool = Field(default=True, description="Download MP3 audio files.")
    download_wav: bool = Field(default=False, description="Download WAV audio files (requires Pro/Premier).")
    download_mp4: bool = Field(default=False, description="Download MP4 video files.")
    include_cover_art: bool = Field(default=True, description="Download album cover art.")
    include_lyrics: bool = Field(default=True, description="Generate plain text lyrics in metadata.")
    include_synced_lyrics: bool = Field(default=True, description="Generate .lrc synced lyrics files.")
    embed_id3_tags: bool = Field(default=True, description="Embed ID3 metadata tags into MP3 files.")
    include_json: bool = Field(default=True, description="Save raw API response as .json alongside .txt.")

    # Performance settings
    workers: int = Field(default=5, ge=1, le=16, description="Number of parallel download workers.")
    skip_existing: bool = Field(default=True, description="Skip files that have already been downloaded.")
    api_delay: float = Field(default=0.2, ge=0.0, le=10.0, description="Delay between API requests (seconds).")
    cdn_delay: float = Field(default=0.1, ge=0.0, le=5.0, description="Delay between CDN downloads (seconds).")
    max_retries: int = Field(default=5, ge=1, le=20, description="Maximum retries on failed requests.")

    # Dashboard settings
    dashboard_port: int = Field(default=8484, ge=1024, le=65535, description="Port for the local web dashboard.")

    # Filter defaults (applied when not overridden by CLI)
    default_liked_only: bool = Field(default=False, description="Only download liked songs by default.")

    model_config = {"json_schema_extra": {"title": "Suno Song Downloaderist Configuration"}}

    @field_validator("output_dir", mode="before")
    @classmethod
    def expand_output_dir(cls, v: Any) -> Path:
        """Expand ~ and environment variables in output directory path."""
        if isinstance(v, str):
            return Path(v).expanduser()
        if isinstance(v, Path):
            return v.expanduser()
        return v

    @property
    def formats_description(self) -> str:
        """Human-readable description of enabled download formats."""
        formats = []
        if self.download_mp3:
            formats.append("MP3")
        if self.download_wav:
            formats.append("WAV")
        if self.download_mp4:
            formats.append("MP4")
        return ", ".join(formats) if formats else "None"


def get_config_path() -> Path:
    """Get the path to the configuration file.

    Returns:
        Path to ~/.suno_downloaderist/config.json
    """
    return get_config_dir() / CONFIG_FILENAME


def load_config() -> AppConfig:
    """Load configuration from disk, falling back to defaults.

    Returns:
        AppConfig instance with loaded or default values.
    """
    config_path = get_config_path()

    if config_path.exists():
        try:
            raw = json.loads(config_path.read_text(encoding="utf-8"))
            config = AppConfig.model_validate(raw)
            logger.debug("Loaded configuration from %s", config_path)
            return config
        except (json.JSONDecodeError, ValueError) as exc:
            logger.warning(
                "Failed to load config from %s: %s. Using defaults.",
                config_path,
                exc,
            )

    return AppConfig()


def save_config(config: AppConfig) -> None:
    """Save configuration to disk.

    Args:
        config: AppConfig instance to persist.
    """
    config_path = get_config_path()

    # Serialize with Path objects as strings
    data = config.model_dump(mode="json")
    data["output_dir"] = str(config.output_dir)

    config_path.write_text(
        json.dumps(data, indent=2, default=str),
        encoding="utf-8",
    )
    logger.debug("Saved configuration to %s", config_path)


def reset_config() -> AppConfig:
    """Reset configuration to defaults and save.

    Returns:
        Fresh AppConfig with default values.
    """
    config = AppConfig()
    save_config(config)
    logger.info("Configuration reset to defaults.")
    return config
