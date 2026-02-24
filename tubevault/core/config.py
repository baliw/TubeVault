"""Global configuration management for TubeVault."""

import json
import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tubevault.utils.helpers import ensure_dir, tubevault_root

logger = logging.getLogger(__name__)

DEFAULT_CONFIG: dict[str, Any] = {
    "channels": [],
    "anthropic_api_key_env": "ANTHROPIC_API_KEY",
    "download_quality": "1080p",
    "max_concurrent_downloads": 2,
}


def config_path() -> Path:
    """Return the path to config.json.

    Returns:
        Path to ~/TubeVault/config.json.
    """
    return tubevault_root() / "config.json"


def load_config() -> dict[str, Any]:
    """Load and return the global config, creating defaults if missing.

    Returns:
        Config dict.
    """
    path = config_path()
    if not path.exists():
        save_config(DEFAULT_CONFIG.copy())
        return DEFAULT_CONFIG.copy()
    try:
        with path.open() as f:
            data = json.load(f)
        # Merge any missing keys from defaults
        for key, value in DEFAULT_CONFIG.items():
            data.setdefault(key, value)
        return data
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Corrupted config.json — backing up and reinitializing: %s", exc)
        _backup_file(path)
        save_config(DEFAULT_CONFIG.copy())
        return DEFAULT_CONFIG.copy()


def save_config(config: dict[str, Any]) -> None:
    """Persist the config dict to disk.

    Args:
        config: Config dict to save.
    """
    path = config_path()
    ensure_dir(path.parent)
    with path.open("w") as f:
        json.dump(config, f, indent=2)


def add_channel(url: str, name: str) -> dict[str, Any]:
    """Add a channel to the config.

    Args:
        url: Channel URL (e.g. https://www.youtube.com/@handle).
        name: Display name / slug for the channel.

    Returns:
        The new channel entry dict.
    """
    config = load_config()
    entry = {
        "name": name,
        "url": url,
        "added_date": datetime.now(timezone.utc).isoformat(),
        "auto_sync": True,
    }
    config["channels"].append(entry)
    save_config(config)
    return entry


def remove_channel(name: str) -> bool:
    """Remove a channel from the config by name.

    Args:
        name: Channel name/slug to remove.

    Returns:
        True if removed, False if not found.
    """
    config = load_config()
    original_len = len(config["channels"])
    config["channels"] = [c for c in config["channels"] if c["name"] != name]
    if len(config["channels"]) < original_len:
        save_config(config)
        return True
    return False


def _backup_file(path: Path) -> None:
    """Back up a file by appending .bak to its name.

    Args:
        path: File to back up.
    """
    backup = path.with_suffix(path.suffix + ".bak")
    try:
        shutil.copy2(path, backup)
        logger.info("Backed up %s to %s", path, backup)
    except OSError as exc:
        logger.error("Failed to back up %s: %s", path, exc)
