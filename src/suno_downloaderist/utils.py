"""Shared utility functions for Suno Song Downloaderist."""

from __future__ import annotations

import logging
import platform
import re
import sys
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    console = Console(legacy_windows=False)
else:
    console = Console()

# Realistic Chrome user agent for HTTP requests
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/128.0.0.0 Safari/537.36"
)

# Characters illegal in filenames across Windows, macOS, and Linux
_ILLEGAL_CHARS = re.compile(r'[\\/:*?"<>|\x00-\x1f]')
# Windows reserved device names
_RESERVED_NAMES = frozenset({
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
})

MAX_FILENAME_LENGTH = 200


def setup_logging(verbose: bool = False) -> None:
    """Configure application logging with rich handler.

    Args:
        verbose: If True, sets log level to DEBUG. Otherwise INFO.
    """
    level = logging.DEBUG if verbose else logging.INFO

    logging.basicConfig(
        level=level,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[
            RichHandler(
                console=console,
                show_path=verbose,
                markup=True,
                rich_tracebacks=True,
            )
        ],
    )

    # Quiet down noisy libraries
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("playwright").setLevel(logging.WARNING)
    logging.getLogger("uvicorn").setLevel(logging.WARNING)


def format_duration(seconds: float) -> str:
    """Format a duration in seconds as a human-readable M:SS string.

    Args:
        seconds: Duration in seconds.

    Returns:
        Formatted string like '3:42'.
    """
    if seconds < 0:
        return "0:00"
    total_seconds = int(seconds)
    minutes = total_seconds // 60
    secs = total_seconds % 60
    return f"{minutes}:{secs:02d}"


def format_bytes(byte_count: int | float) -> str:
    """Format a byte count as a human-readable string.

    Args:
        byte_count: Number of bytes.

    Returns:
        Formatted string like '14.2 MB'.
    """
    if byte_count < 0:
        return "0 B"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(byte_count) < 1024:
            if unit == "B":
                return f"{int(byte_count)} {unit}"
            return f"{byte_count:.1f} {unit}"
        byte_count /= 1024
    return f"{byte_count:.1f} PB"


def format_speed(bytes_per_sec: float) -> str:
    """Format a download speed as a human-readable string.

    Args:
        bytes_per_sec: Speed in bytes per second.

    Returns:
        Formatted string like '2.4 MB/s'.
    """
    return f"{format_bytes(bytes_per_sec)}/s"


def format_eta(seconds: float) -> str:
    """Format an ETA in seconds as a human-readable string.

    Args:
        seconds: Estimated time remaining in seconds.

    Returns:
        Formatted string like '2m 30s' or '1h 5m'.
    """
    if seconds < 0 or seconds > 86400:
        return "calculating..."
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        minutes = seconds // 60
        secs = seconds % 60
        return f"{minutes}m {secs}s"
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    return f"{hours}h {minutes}m"


def sanitize_filename(name: str) -> str:
    """Remove or replace characters that are illegal in filenames.

    Handles Windows, macOS, and Linux filesystem restrictions.
    Truncates to MAX_FILENAME_LENGTH characters.

    Args:
        name: The raw filename to sanitize.

    Returns:
        A safe filename string. Falls back to 'untitled' if empty after sanitization.
    """
    if not name or not name.strip():
        return "untitled"

    # Replace illegal characters with underscores
    sanitized = _ILLEGAL_CHARS.sub("_", name)

    # Strip leading/trailing whitespace and dots (Windows restriction)
    sanitized = sanitized.strip().strip(".")

    # Handle Windows reserved device names
    stem = sanitized.split(".")[0].upper()
    if stem in _RESERVED_NAMES:
        sanitized = f"_{sanitized}"

    # Truncate to max length
    if len(sanitized) > MAX_FILENAME_LENGTH:
        sanitized = sanitized[:MAX_FILENAME_LENGTH].rstrip(". ")

    # Final fallback
    if not sanitized:
        return "untitled"

    return sanitized


def ensure_dir(path: Path) -> Path:
    """Create a directory (and parents) if it doesn't exist.

    Args:
        path: Directory path to ensure exists.

    Returns:
        The path that was created/verified.
    """
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_user_agent() -> str:
    """Return a realistic Chrome user agent string.

    Returns:
        User agent string mimicking Chrome on Windows.
    """
    return _USER_AGENT


def get_config_dir() -> Path:
    """Get the application configuration directory.

    Returns:
        Path to ~/.suno_downloaderist/
    """
    config_dir = Path.home() / ".suno_downloaderist"
    ensure_dir(config_dir)
    return config_dir


def get_default_output_dir() -> Path:
    """Get the default download output directory.

    Returns:
        Path to ~/Music/SunoDownloaderist/
    """
    return Path.home() / "Music" / "SunoDownloaderist"


def is_windows() -> bool:
    """Check if the current platform is Windows."""
    return platform.system() == "Windows"
