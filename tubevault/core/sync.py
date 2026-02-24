"""Orchestrator: sync all channels (download + transcript + AI summary)."""

import asyncio
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from tubevault.core.config import load_config
from tubevault.core.database import (
    load_library,
    mark_library_synced,
    save_metadata,
    save_summary,
    save_transcript,
    upsert_video,
    video_dir,
)
from tubevault.core.downloader import download_video, fetch_channel_videos
from tubevault.core.summarizer import generate_summary
from tubevault.core.transcript import fetch_transcript

logger = logging.getLogger(__name__)


@dataclass
class VideoProgress:
    """Progress state for a single video being synced."""

    video_id: str
    title: str
    download: float = 0.0        # 0.0–1.0
    transcript: str = "pending"  # pending | in_progress | done | skipped | error
    summary: str = "pending"     # pending | in_progress | done | skipped | error


@dataclass
class ChannelSyncProgress:
    """Progress state for a channel sync operation."""

    channel_name: str
    total: int = 0
    completed: int = 0
    current_video: VideoProgress | None = None
    done: bool = False
    error: str | None = None


SyncCallback = Callable[[ChannelSyncProgress], None]


async def sync_channel(
    channel_name: str,
    channel_url: str,
    quality: str = "1080p",
    max_concurrent: int = 2,
    progress_callback: SyncCallback | None = None,
) -> None:
    """Sync a single channel: fetch video list, download new videos, transcribe, summarize.

    Args:
        channel_name: Channel slug.
        channel_url: YouTube channel URL.
        quality: Download quality string.
        max_concurrent: Max concurrent download workers.
        progress_callback: Optional callback invoked on each state change.
    """
    prog = ChannelSyncProgress(channel_name=channel_name)
    _emit(progress_callback, prog)

    logger.info("Fetching video list for channel %s…", channel_name)
    try:
        remote_videos = await fetch_channel_videos(channel_url)
    except Exception as exc:
        prog.error = str(exc)
        prog.done = True
        _emit(progress_callback, prog)
        logger.error("Failed to fetch channel videos: %s", exc)
        return

    library = load_library(channel_name)
    existing_ids = {v["video_id"] for v in library.get("videos", [])}

    # New videos not yet in library
    new_videos = [v for v in remote_videos if v["video_id"] not in existing_ids]

    # Existing videos that are missing transcript or summary
    backfill_videos = [
        v for v in library.get("videos", [])
        if not v.get("has_transcript") or not v.get("has_summary")
    ]

    to_process = new_videos + backfill_videos
    prog.total = len(to_process)
    _emit(progress_callback, prog)

    if not to_process:
        logger.info("Channel %s is up to date.", channel_name)
        mark_library_synced(channel_name)
        prog.done = True
        _emit(progress_callback, prog)
        return

    # Upsert new video stubs into library
    for v in new_videos:
        upsert_video(channel_name, v)

    semaphore = asyncio.Semaphore(max_concurrent)

    async def _process_one(video: dict[str, Any]) -> None:
        async with semaphore:
            try:
                await _process_video(channel_name, video, quality, prog, progress_callback)
            except Exception as exc:
                logger.error("Failed to process video %s: %s", video.get("video_id"), exc)
            prog.completed += 1
            _emit(progress_callback, prog)

    await asyncio.gather(*[_process_one(v) for v in to_process], return_exceptions=True)

    mark_library_synced(channel_name)
    prog.done = True
    prog.current_video = None
    _emit(progress_callback, prog)
    logger.info("Channel %s sync complete. Processed %d videos.", channel_name, len(to_process))


async def _process_video(
    channel_name: str,
    video: dict[str, Any],
    quality: str,
    prog: ChannelSyncProgress,
    callback: SyncCallback | None,
) -> None:
    """Process a single video: download, transcript, summary.

    Args:
        channel_name: Channel slug.
        video: Video entry dict.
        quality: Download quality.
        prog: Shared channel progress object.
        callback: Progress callback.
    """
    video_id = video["video_id"]
    title = video.get("title", video_id)
    vp = VideoProgress(video_id=video_id, title=title)
    prog.current_video = vp
    _emit(callback, prog)

    # --- Download ---
    if not video.get("has_video"):
        mp4_path = await download_video(
            channel_name,
            video_id,
            quality=quality,
            progress_callback=lambda p: _update_download(vp, p, prog, callback),
        )
        if mp4_path:
            size_mb = mp4_path.stat().st_size / (1024 * 1024)
            upsert_video(channel_name, {"video_id": video_id, "has_video": True, "file_size_mb": round(size_mb, 2)})
            vp.download = 1.0
        else:
            vp.download = -1.0  # error sentinel
        _emit(callback, prog)
    else:
        vp.download = 1.0

    # --- Transcript ---
    if not video.get("has_transcript"):
        vp.transcript = "in_progress"
        _emit(callback, prog)
        segments = await fetch_transcript(channel_name, video_id)
        if segments:
            save_transcript(channel_name, video_id, segments)
            upsert_video(channel_name, {"video_id": video_id, "has_transcript": True})
            vp.transcript = "done"
        else:
            upsert_video(channel_name, {"video_id": video_id, "has_transcript": False})
            vp.transcript = "skipped"
        _emit(callback, prog)
    else:
        vp.transcript = "done"

    # --- Summary ---
    if not video.get("has_summary") and vp.transcript == "done":
        vp.summary = "in_progress"
        _emit(callback, prog)

        from tubevault.core.database import load_transcript as _load_transcript
        segments = _load_transcript(channel_name, video_id)
        if segments:
            summary = await generate_summary(video_id, segments, title=title)
            if summary:
                save_summary(channel_name, video_id, summary)
                upsert_video(channel_name, {"video_id": video_id, "has_summary": True})
                vp.summary = "done"
            else:
                upsert_video(channel_name, {"video_id": video_id, "has_summary": False})
                vp.summary = "error"
        else:
            vp.summary = "skipped"
        _emit(callback, prog)
    elif vp.transcript == "skipped":
        vp.summary = "skipped"
    else:
        vp.summary = "done"


def _update_download(
    vp: VideoProgress,
    progress: float,
    prog: ChannelSyncProgress,
    callback: SyncCallback | None,
) -> None:
    vp.download = progress
    _emit(callback, prog)


def _emit(callback: SyncCallback | None, prog: ChannelSyncProgress) -> None:
    if callback:
        try:
            callback(prog)
        except Exception as exc:
            logger.debug("Progress callback error: %s", exc)


async def sync_all_channels(
    progress_callback: SyncCallback | None = None,
) -> None:
    """Sync all channels configured in config.json.

    Args:
        progress_callback: Optional callback for progress updates.
    """
    config = load_config()
    channels = config.get("channels", [])
    quality = config.get("download_quality", "1080p")
    max_concurrent = config.get("max_concurrent_downloads", 2)

    for channel in channels:
        if not channel.get("auto_sync", True):
            continue
        await sync_channel(
            channel_name=channel["name"],
            channel_url=channel["url"],
            quality=quality,
            max_concurrent=max_concurrent,
            progress_callback=progress_callback,
        )
