"""Read/write library.json and collection.json for TubeVault."""

import json
import logging
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tubevault.utils.helpers import ensure_dir, tubevault_root

logger = logging.getLogger(__name__)

# Maximum number of video entries stored in a single library page file.
LIBRARY_PAGE_SIZE = 100

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


def library_page_path(channel_name: str, page_num: int) -> Path:
    """Return the path to a numbered library page file.

    Args:
        channel_name: Channel slug.
        page_num: 1-based page number.

    Returns:
        Path to library_NNN.json.
    """
    return channel_dir(channel_name) / f"library_{page_num:03d}.json"


def _legacy_library_path(channel_name: str) -> Path:
    """Return the path to the legacy library.json file."""
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
# Library — paginated page files
# ---------------------------------------------------------------------------

def _list_page_nums_raw(channel_name: str) -> list[int]:
    """Glob for library_NNN.json files without triggering migration.

    Used internally by _migrate_library_if_needed to avoid circular calls.
    """
    cdir = channel_dir(channel_name)
    nums: list[int] = []
    for p in cdir.glob("library_*.json"):
        m = re.match(r"^library_(\d+)\.json$", p.name)
        if m:
            nums.append(int(m.group(1)))
    return sorted(nums)


def list_library_page_nums(channel_name: str) -> list[int]:
    """Return sorted list of existing library page numbers (1-based).

    Triggers migration from legacy library.json if it has not yet happened.

    Args:
        channel_name: Channel slug.

    Returns:
        Ascending list of page numbers for which library_NNN.json exists.
    """
    _migrate_library_if_needed(channel_name)
    return _list_page_nums_raw(channel_name)


def _migrate_library_if_needed(channel_name: str) -> None:
    """One-time migration: split legacy library.json into library_NNN.json pages.

    Safe to call repeatedly — exits immediately once migration is done.

    Args:
        channel_name: Channel slug.
    """
    legacy = _legacy_library_path(channel_name)
    if not legacy.exists():
        return  # Nothing to migrate

    existing_pages = _list_page_nums_raw(channel_name)
    if existing_pages:
        # Migration already completed; clean up the old file.
        _backup_json(legacy)
        try:
            legacy.unlink()
        except OSError:
            pass
        return

    logger.info("Migrating library.json → paged format for channel %s", channel_name)
    default = {**EMPTY_LIBRARY, "channel_name": channel_name}
    data = _load_json(legacy, default)
    videos = sorted(data.get("videos", []), key=lambda v: v.get("upload_date", ""))
    last_synced = data.get("last_synced")
    ch_name = data.get("channel_name", channel_name)

    if videos:
        for chunk_start in range(0, len(videos), LIBRARY_PAGE_SIZE):
            page_num = chunk_start // LIBRARY_PAGE_SIZE + 1
            chunk = videos[chunk_start : chunk_start + LIBRARY_PAGE_SIZE]
            # Store last_synced only on the highest (last-written) page so
            # load_library's "last one wins" iteration picks it up correctly.
            is_last_page = chunk_start + LIBRARY_PAGE_SIZE >= len(videos)
            page_data: dict[str, Any] = {
                "channel_name": ch_name,
                "last_synced": last_synced if is_last_page else None,
                "videos": chunk,
            }
            _save_json(library_page_path(channel_name, page_num), page_data)

    # Remove the legacy file (back it up first).
    _backup_json(legacy)
    try:
        legacy.unlink()
    except OSError:
        pass


def load_library_page(channel_name: str, page_num: int) -> dict[str, Any]:
    """Load a single library page file.

    Args:
        channel_name: Channel slug.
        page_num: 1-based page number.

    Returns:
        Page dict with ``channel_name``, ``last_synced``, and ``videos`` keys.
    """
    _migrate_library_if_needed(channel_name)
    default = {**EMPTY_LIBRARY, "channel_name": channel_name}
    path = library_page_path(channel_name, page_num)
    data = _load_json(path, default)
    data.setdefault("channel_name", channel_name)
    data.setdefault("videos", [])
    return data


def save_library_page(channel_name: str, page_num: int, data: dict[str, Any]) -> None:
    """Save a single library page file.

    Args:
        channel_name: Channel slug.
        page_num: 1-based page number.
        data: Page dict to persist.
    """
    _save_json(library_page_path(channel_name, page_num), data)


def load_library(channel_name: str) -> dict[str, Any]:
    """Load the complete library by merging all page files.

    For progressive / incremental loading in the UI, use
    ``list_library_page_nums`` + ``load_library_page`` directly.

    Args:
        channel_name: Channel slug.

    Returns:
        Merged library dict with all videos across all pages.
    """
    _migrate_library_if_needed(channel_name)
    page_nums = list_library_page_nums(channel_name)

    if not page_nums:
        return {**EMPTY_LIBRARY, "channel_name": channel_name}

    all_videos: list[dict[str, Any]] = []
    last_synced: str | None = None

    for pn in page_nums:
        page = load_library_page(channel_name, pn)
        all_videos.extend(page.get("videos", []))
        if page.get("last_synced"):
            last_synced = page["last_synced"]  # highest page wins

    return {
        "channel_name": channel_name,
        "last_synced": last_synced,
        "videos": all_videos,
    }


def get_video_entry(channel_name: str, video_id: str) -> dict[str, Any] | None:
    """Retrieve a single video entry from the library.

    Searches pages from newest to oldest for efficiency.

    Args:
        channel_name: Channel slug.
        video_id: YouTube video ID.

    Returns:
        Video entry dict, or None if not found.
    """
    _migrate_library_if_needed(channel_name)
    for pn in reversed(list_library_page_nums(channel_name)):
        page = load_library_page(channel_name, pn)
        for v in page.get("videos", []):
            if v["video_id"] == video_id:
                return v
    return None


def upsert_video(channel_name: str, entry: dict[str, Any]) -> None:
    """Insert or update a video entry across the paginated library files.

    - If the video already exists in any page, that page is updated in-place.
    - If the video is new, it is appended to the highest-numbered page (or a
      new page is created if the last page is already at capacity).

    Args:
        channel_name: Channel slug.
        entry: Video entry dict containing at minimum ``video_id``.
    """
    _migrate_library_if_needed(channel_name)
    video_id = entry["video_id"]
    page_nums = list_library_page_nums(channel_name)

    # Search existing pages, newest first (most likely to have recent videos).
    for pn in reversed(page_nums):
        page = load_library_page(channel_name, pn)
        for i, v in enumerate(page["videos"]):
            if v["video_id"] == video_id:
                page["videos"][i] = {**v, **entry}
                save_library_page(channel_name, pn, page)
                return

    # New video — add to the last page or create a new one.
    entry.setdefault("added_date", datetime.now(timezone.utc).isoformat())

    if not page_nums:
        _save_json(
            library_page_path(channel_name, 1),
            {"channel_name": channel_name, "last_synced": None, "videos": [entry]},
        )
        return

    last_pn = page_nums[-1]
    last_page = load_library_page(channel_name, last_pn)

    if len(last_page["videos"]) < LIBRARY_PAGE_SIZE:
        last_page["videos"].append(entry)
        save_library_page(channel_name, last_pn, last_page)
    else:
        new_pn = last_pn + 1
        _save_json(
            library_page_path(channel_name, new_pn),
            {"channel_name": channel_name, "last_synced": None, "videos": [entry]},
        )


def batch_update_upload_dates(channel_name: str, date_map: dict[str, str]) -> int:
    """Backfill upload_date for library entries that are currently empty.

    Reads each page once, patches every entry whose video_id appears in
    *date_map* and whose current upload_date is falsy, then writes the page
    once only if any entry was changed.  O(pages) disk operations regardless
    of how many dates are updated.

    Args:
        channel_name: Channel slug.
        date_map: Mapping of ``video_id`` → ``upload_date`` (YYYY-MM-DD).

    Returns:
        Number of library entries updated.
    """
    _migrate_library_if_needed(channel_name)
    updated = 0
    for pn in _list_page_nums_raw(channel_name):
        page = load_library_page(channel_name, pn)
        changed = False
        for v in page["videos"]:
            vid = v.get("video_id", "")
            if vid in date_map and not v.get("upload_date"):
                v["upload_date"] = date_map[vid]
                updated += 1
                changed = True
        if changed:
            save_library_page(channel_name, pn, page)
    return updated


def mark_library_synced(channel_name: str) -> None:
    """Update last_synced timestamp in the highest-numbered library page.

    Args:
        channel_name: Channel slug.
    """
    _migrate_library_if_needed(channel_name)
    page_nums = list_library_page_nums(channel_name)
    now = datetime.now(timezone.utc).isoformat()

    if not page_nums:
        # No videos yet; create page 1 to record the sync timestamp.
        _save_json(
            library_page_path(channel_name, 1),
            {"channel_name": channel_name, "last_synced": now, "videos": []},
        )
        return

    highest = page_nums[-1]
    page = load_library_page(channel_name, highest)
    page["last_synced"] = now
    save_library_page(channel_name, highest, page)


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
