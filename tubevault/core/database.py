"""Read/write library.json and collection.json for TubeVault."""

import json
import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tubevault.utils.helpers import ensure_dir, tubevault_root

logger = logging.getLogger(__name__)

EMPTY_LIBRARY: dict[str, Any] = {
    "channel_name": "",
    "last_synced": None,
    "videos": [],
}

EMPTY_COLLECTION: dict[str, Any] = {
    "channel_name": "",
    "items": [],
}


def channel_dir(channel_name: str) -> Path:
    """Return the directory for a channel's data.

    Args:
        channel_name: Channel slug/name.

    Returns:
        Path to ~/TubeVault/videos/<channel_name>/.
    """
    path = tubevault_root() / "videos" / channel_name
    ensure_dir(path)
    return path


def library_path(channel_name: str) -> Path:
    """Return the path to library.json for a channel."""
    return channel_dir(channel_name) / "library.json"


def collection_path(channel_name: str) -> Path:
    """Return the path to collection.json for a channel."""
    return channel_dir(channel_name) / "collection.json"


def _load_json(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    """Load a JSON file, recovering from corruption.

    Args:
        path: File path.
        default: Default value if file is missing or corrupted.

    Returns:
        Loaded dict.
    """
    if not path.exists():
        return default.copy()
    try:
        with path.open() as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Corrupted %s — backing up and reinitializing: %s", path, exc)
        _backup_json(path)
        return default.copy()


def _save_json(path: Path, data: dict[str, Any]) -> None:
    """Persist data as JSON to path.

    Args:
        path: Destination file path.
        data: Data to serialize.
    """
    ensure_dir(path.parent)
    with path.open("w") as f:
        json.dump(data, f, indent=2)


def _backup_json(path: Path) -> None:
    backup = path.with_suffix(".json.bak")
    try:
        shutil.copy2(path, backup)
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Library
# ---------------------------------------------------------------------------

def load_library(channel_name: str) -> dict[str, Any]:
    """Load library.json for a channel.

    Args:
        channel_name: Channel slug.

    Returns:
        Library dict.
    """
    default = {**EMPTY_LIBRARY, "channel_name": channel_name}
    data = _load_json(library_path(channel_name), default)
    data.setdefault("channel_name", channel_name)
    data.setdefault("videos", [])
    return data


def save_library(channel_name: str, library: dict[str, Any]) -> None:
    """Save library.json for a channel.

    Args:
        channel_name: Channel slug.
        library: Library dict to save.
    """
    _save_json(library_path(channel_name), library)


def get_video_entry(channel_name: str, video_id: str) -> dict[str, Any] | None:
    """Retrieve a single video entry from the library.

    Args:
        channel_name: Channel slug.
        video_id: YouTube video ID.

    Returns:
        Video entry dict, or None if not found.
    """
    library = load_library(channel_name)
    for video in library["videos"]:
        if video["video_id"] == video_id:
            return video
    return None


def upsert_video(channel_name: str, entry: dict[str, Any]) -> None:
    """Insert or update a video entry in library.json.

    Args:
        channel_name: Channel slug.
        entry: Video entry dict containing at minimum ``video_id``.
    """
    library = load_library(channel_name)
    videos = library["videos"]
    for i, v in enumerate(videos):
        if v["video_id"] == entry["video_id"]:
            videos[i] = {**v, **entry}
            save_library(channel_name, library)
            return
    entry.setdefault("added_date", datetime.now(timezone.utc).isoformat())
    videos.append(entry)
    save_library(channel_name, library)


def mark_library_synced(channel_name: str) -> None:
    """Update last_synced timestamp in library.json.

    Args:
        channel_name: Channel slug.
    """
    library = load_library(channel_name)
    library["last_synced"] = datetime.now(timezone.utc).isoformat()
    save_library(channel_name, library)


# ---------------------------------------------------------------------------
# Collection
# ---------------------------------------------------------------------------

def load_collection(channel_name: str) -> dict[str, Any]:
    """Load collection.json for a channel.

    Args:
        channel_name: Channel slug.

    Returns:
        Collection dict.
    """
    default = {**EMPTY_COLLECTION, "channel_name": channel_name}
    data = _load_json(collection_path(channel_name), default)
    data.setdefault("channel_name", channel_name)
    data.setdefault("items", [])
    return data


def save_collection(channel_name: str, collection: dict[str, Any]) -> None:
    """Save collection.json for a channel.

    Args:
        channel_name: Channel slug.
        collection: Collection dict to save.
    """
    _save_json(collection_path(channel_name), collection)


def collection_add_video(channel_name: str, video_id: str) -> bool:
    """Add a video to the collection (no-op if already present).

    Args:
        channel_name: Channel slug.
        video_id: YouTube video ID.

    Returns:
        True if added, False if already present.
    """
    collection = load_collection(channel_name)
    for item in collection["items"]:
        if item.get("type") == "video" and item.get("video_id") == video_id:
            return False
    collection["items"].append(
        {
            "type": "video",
            "video_id": video_id,
            "note": "",
            "added_date": datetime.now(timezone.utc).isoformat(),
        }
    )
    save_collection(channel_name, collection)
    return True


def collection_remove_item(channel_name: str, index: int) -> None:
    """Remove an item from the collection by index.

    Args:
        channel_name: Channel slug.
        index: 0-based index of the item to remove.
    """
    collection = load_collection(channel_name)
    if 0 <= index < len(collection["items"]):
        collection["items"].pop(index)
        save_collection(channel_name, collection)


def collection_move_item(channel_name: str, index: int, direction: int) -> None:
    """Move a collection item up (-1) or down (+1).

    Args:
        channel_name: Channel slug.
        index: Current index.
        direction: -1 for up, +1 for down.
    """
    collection = load_collection(channel_name)
    items = collection["items"]
    new_index = index + direction
    if 0 <= new_index < len(items):
        items[index], items[new_index] = items[new_index], items[index]
        save_collection(channel_name, collection)


def collection_insert_header(channel_name: str, index: int, text: str) -> None:
    """Insert a section header before the given index.

    Args:
        channel_name: Channel slug.
        index: Position to insert before.
        text: Header text.
    """
    import uuid

    collection = load_collection(channel_name)
    header = {
        "type": "section_header",
        "text": text,
        "id": f"sec_{uuid.uuid4().hex[:8]}",
    }
    collection["items"].insert(index, header)
    save_collection(channel_name, collection)


def collection_set_note(channel_name: str, video_id: str, note: str) -> None:
    """Set the note on a collection video item.

    Args:
        channel_name: Channel slug.
        video_id: YouTube video ID.
        note: Note text.
    """
    collection = load_collection(channel_name)
    for item in collection["items"]:
        if item.get("type") == "video" and item.get("video_id") == video_id:
            item["note"] = note
            save_collection(channel_name, collection)
            return


# ---------------------------------------------------------------------------
# Summary / metadata helpers
# ---------------------------------------------------------------------------

def video_dir(channel_name: str, video_id: str) -> Path:
    """Return the directory for a specific video's files.

    Args:
        channel_name: Channel slug.
        video_id: YouTube video ID.

    Returns:
        Path to ~/TubeVault/videos/<channel>/<video_id>/.
    """
    path = channel_dir(channel_name) / video_id
    ensure_dir(path)
    return path


def load_summary(channel_name: str, video_id: str) -> dict[str, Any] | None:
    """Load summary.json for a video.

    Args:
        channel_name: Channel slug.
        video_id: YouTube video ID.

    Returns:
        Summary dict, or None if not found.
    """
    path = video_dir(channel_name, video_id) / "summary.json"
    if not path.exists():
        return None
    return _load_json(path, {})


def save_summary(channel_name: str, video_id: str, summary: dict[str, Any]) -> None:
    """Save summary.json for a video.

    Args:
        channel_name: Channel slug.
        video_id: YouTube video ID.
        summary: Summary dict.
    """
    path = video_dir(channel_name, video_id) / "summary.json"
    _save_json(path, summary)


def load_transcript(channel_name: str, video_id: str) -> list[dict[str, Any]] | None:
    """Load transcript.json for a video.

    Args:
        channel_name: Channel slug.
        video_id: YouTube video ID.

    Returns:
        List of transcript segments, or None if not found.
    """
    path = video_dir(channel_name, video_id) / "transcript.json"
    if not path.exists():
        return None
    data = _load_json(path, {})
    return data.get("segments") if isinstance(data, dict) else data


def save_transcript(channel_name: str, video_id: str, segments: list[dict[str, Any]]) -> None:
    """Save transcript.json for a video.

    Args:
        channel_name: Channel slug.
        video_id: YouTube video ID.
        segments: List of transcript segment dicts with text and start keys.
    """
    path = video_dir(channel_name, video_id) / "transcript.json"
    _save_json(path, {"segments": segments})


def load_metadata(channel_name: str, video_id: str) -> dict[str, Any] | None:
    """Load metadata.json for a video.

    Args:
        channel_name: Channel slug.
        video_id: YouTube video ID.

    Returns:
        Metadata dict, or None if not found.
    """
    path = video_dir(channel_name, video_id) / "metadata.json"
    if not path.exists():
        return None
    return _load_json(path, {})


def save_metadata(channel_name: str, video_id: str, metadata: dict[str, Any]) -> None:
    """Save metadata.json for a video.

    Args:
        channel_name: Channel slug.
        video_id: YouTube video ID.
        metadata: Metadata dict.
    """
    path = video_dir(channel_name, video_id) / "metadata.json"
    _save_json(path, metadata)
