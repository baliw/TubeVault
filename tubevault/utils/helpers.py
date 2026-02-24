"""Shared utility functions for TubeVault."""

import logging
from datetime import timedelta
from pathlib import Path

logger = logging.getLogger(__name__)


def format_duration(seconds: int) -> str:
    """Format duration in seconds to HH:MM:SS or MM:SS string.

    Args:
        seconds: Duration in seconds.

    Returns:
        Formatted duration string.
    """
    td = timedelta(seconds=seconds)
    total_seconds = int(td.total_seconds())
    hours, remainder = divmod(total_seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def format_timestamp(seconds: int) -> str:
    """Format seconds to MM:SS timestamp string.

    Args:
        seconds: Time in seconds.

    Returns:
        MM:SS formatted string.
    """
    minutes, secs = divmod(int(seconds), 60)
    return f"{minutes:02d}:{secs:02d}"


def ensure_dir(path: Path) -> Path:
    """Ensure a directory exists, creating it if necessary.

    Args:
        path: Directory path to ensure.

    Returns:
        The path, guaranteed to exist.
    """
    path.mkdir(parents=True, exist_ok=True)
    return path


def tubevault_root() -> Path:
    """Return the root TubeVault data directory.

    Returns:
        Path to ~/TubeVault/.
    """
    root = Path.home() / "TubeVault"
    ensure_dir(root)
    return root
