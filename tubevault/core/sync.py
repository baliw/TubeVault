"""Orchestrator: sync all channels (download + transcript + AI summary)."""

import asyncio
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from tubevault.core.config import QUALITY_MAP, load_config
from tubevault.core.database import (
    load_library,
    mark_library_synced,
    save_summary,
    save_transcript,
    upsert_video,
    video_dir,
)
from tubevault.core.downloader import download_video, fetch_channel_videos
from tubevault.core.summarizer import generate_summary
from tubevault.core.transcript import fetch_transcript
from tubevault.utils.helpers import load_proxy_url

logger = logging.getLogger(__name__)

# Seconds to wait between successive download requests (no-proxy mode only).
INTER_REQUEST_DELAY = 10

# Number of concurrent download threads when a proxy is configured.
PROXY_CONCURRENCY = 4


@dataclass
class VideoProgress:
    """Progress state for a single video being synced."""

    video_id: str
    title: str
    channel_name: str = ""       # which channel this video belongs to
    download: float = 0.0        # 0.0–1.0
    transcript: str = "pending"  # pending | in_progress | done | skipped | error
    summary: str = "pending"     # pending | in_progress | done | skipped | error


@dataclass
class ChannelSyncProgress:
    """Progress state for a channel sync operation."""

    channel_name: str
    total: int = 0
    completed: int = 0
    # Fixed-size list of video slots (always length 4); None = idle slot.
    slots: list[VideoProgress | None] = field(default_factory=list)
    slot_count: int = 1        # how many slots are concurrently active
    done: bool = False
    error: str | None = None
    retry_countdown: int = 0   # seconds remaining in retry wait (0 = not waiting)
    retry_message: str = ""    # human-readable retry status message


SyncCallback = Callable[[ChannelSyncProgress], None]
LogCallback = Callable[[Any], None]
SlotLogCallback = Callable[[int, Any], None]


async def sync_channel(
    channel_name: str,
    channel_url: str,
    quality: str = "1080p",
    max_concurrent: int = 2,
    progress_callback: SyncCallback | None = None,
    log_callback: LogCallback | None = None,
    slot_log_callback: SlotLogCallback | None = None,
) -> None:
    """Sync a single channel: fetch video list, download new videos, transcribe, summarize.

    Args:
        channel_name: Channel slug.
        channel_url: YouTube channel URL.
        quality: Download quality string.
        max_concurrent: Ignored when proxy is configured (PROXY_CONCURRENCY is used instead).
        progress_callback: Optional callback invoked on each state change.
        log_callback: Optional callback for channel-level log lines (routed to slot 0).
        slot_log_callback: Optional callback for per-slot log lines; receives (slot_idx, msg).
    """
    # Always allocate 4 UI slots so the quadrant display is stable.
    NUM_SLOTS = 4
    prog = ChannelSyncProgress(channel_name=channel_name, slots=[None] * NUM_SLOTS)
    _emit(progress_callback, prog)

    _log(log_callback, f"=== Syncing channel: {channel_name} ===")
    proxy = load_proxy_url()
    _log(log_callback, f"Proxy: {proxy}" if proxy else "Proxy: none")
    _log(log_callback, "Fetching video list…")

    concurrency = PROXY_CONCURRENCY if proxy else 1
    prog.slot_count = concurrency

    try:
        remote_videos = await fetch_channel_videos(channel_url, log_callback=log_callback)
    except Exception as exc:
        prog.error = str(exc)
        prog.done = True
        _emit(progress_callback, prog)
        _log(log_callback, f"ERROR fetching channel videos: {exc}")
        logger.error("Failed to fetch channel videos: %s", exc)
        return

    library = load_library(channel_name)
    existing_ids = {v["video_id"] for v in library.get("videos", [])}

    new_videos = [v for v in remote_videos if v["video_id"] not in existing_ids]
    backfill_videos = [
        v for v in library.get("videos", [])
        if not v.get("has_transcript") or not v.get("has_summary")
    ]

    to_process = new_videos + backfill_videos
    prog.total = len(to_process)
    _emit(progress_callback, prog)

    _log(log_callback, f"{len(new_videos)} new videos, {len(backfill_videos)} to backfill")

    if not to_process:
        _log(log_callback, "Channel is up to date.")
        logger.info("Channel %s is up to date.", channel_name)
        mark_library_synced(channel_name)
        prog.done = True
        _emit(progress_callback, prog)
        return

    for v in new_videos:
        upsert_video(channel_name, v)

    semaphore = asyncio.Semaphore(concurrency)
    available_slots: list[int] = list(range(concurrency))

    async def _process_one(video: dict[str, Any]) -> None:
        async with semaphore:
            slot_idx = available_slots.pop(0)

            def _slot_log(msg: Any) -> None:
                if slot_log_callback:
                    try:
                        slot_log_callback(slot_idx, msg)
                    except Exception:
                        pass

            try:
                await _process_video(
                    channel_name, video, quality, prog, slot_idx,
                    progress_callback, _slot_log,
                )
            except Exception as exc:
                msg = f"Failed to process {video.get('video_id')}: {exc}"
                logger.error(msg)
                _slot_log(f"ERROR: {msg}")
            finally:
                prog.slots[slot_idx] = None
                available_slots.append(slot_idx)
            prog.completed += 1
            _emit(progress_callback, prog)

    await asyncio.gather(*[_process_one(v) for v in to_process])

    mark_library_synced(channel_name)
    prog.done = True
    prog.slots = [None] * NUM_SLOTS
    _emit(progress_callback, prog)
    _log(log_callback, f"=== Sync complete: {len(to_process)} videos processed ===")
    logger.info("Channel %s sync complete.", channel_name)


async def _process_video(
    channel_name: str,
    video: dict[str, Any],
    quality: str,
    prog: ChannelSyncProgress,
    slot_idx: int,
    callback: SyncCallback | None,
    log_callback: LogCallback | None,
) -> None:
    """Process a single video: download, transcript, summary."""
    video_id = video["video_id"]
    title = video.get("title", video_id)
    vp = VideoProgress(video_id=video_id, title=title, channel_name=channel_name)
    prog.slots[slot_idx] = vp
    _emit(callback, prog)

    # --- Download ---
    if not video.get("has_video"):
        _log(log_callback, f"--- Downloading: {title} ({video_id}) ---")
        using_proxy = bool(load_proxy_url())
        mp4_path = None

        try:
            mp4_path = await download_video(
                channel_name,
                video_id,
                quality=quality,
                progress_callback=lambda p: _update_download(vp, p, prog, callback),
                log_callback=log_callback,
            )
            if mp4_path is None:
                _log(log_callback, f"Download returned no file for {video_id}")
        except Exception as exc:
            _log(log_callback, f"Download error for {video_id}: {exc}")

        # Pause between requests when not using a proxy.
        if not using_proxy:
            for remaining in range(INTER_REQUEST_DELAY, 0, -1):
                prog.retry_countdown = remaining
                prog.retry_message = f"⏸ Next request in {remaining}s"
                _emit(callback, prog)
                await asyncio.sleep(1)
            prog.retry_countdown = 0
            prog.retry_message = ""
            _emit(callback, prog)

        if mp4_path:
            size_mb = mp4_path.stat().st_size / (1024 * 1024)
            upsert_video(channel_name, {
                "video_id": video_id,
                "has_video": True,
                "file_size_mb": round(size_mb, 2),
            })
            vp.download = 1.0
            _log(log_callback, f"Download complete: {size_mb:.1f} MB")
        else:
            vp.download = -1.0
            _log(log_callback, f"Download failed for {video_id}")
        _emit(callback, prog)
    else:
        vp.download = 1.0

    # --- Transcript ---
    if not video.get("has_transcript"):
        _log(log_callback, f"Fetching transcript for {video_id}…")
        vp.transcript = "in_progress"
        _emit(callback, prog)
        segments = await fetch_transcript(channel_name, video_id, log_callback=log_callback)
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
        _log(log_callback, f"Generating AI summary for {video_id}…")
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
                _log(log_callback, f"Summary generated for {video_id}")
            else:
                upsert_video(channel_name, {"video_id": video_id, "has_summary": False})
                vp.summary = "error"
                _log(log_callback, f"Summary generation failed for {video_id}")
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


def _log(callback: LogCallback | None, msg: Any) -> None:
    if callback:
        try:
            callback(msg)
        except Exception as exc:
            logger.debug("Log callback error: %s", exc)


async def sync_all_channels(
    progress_callback: SyncCallback | None = None,
    log_callback: LogCallback | None = None,
    slot_log_callback: SlotLogCallback | None = None,
) -> None:
    """Sync all auto-sync channels concurrently.

    Threads are distributed across channels so each thread initially works on
    a different channel.  When a channel's queue is exhausted, freed threads
    are reassigned to the channel with the most remaining videos (farthest
    behind).

    Args:
        progress_callback: Optional callback for progress updates.
        log_callback: Optional callback for channel-level log lines (→ slot 0).
        slot_log_callback: Optional callback for per-slot log lines.
    """
    config = load_config()
    channels_cfg = config.get("channels", [])
    proxy = load_proxy_url()
    concurrency = PROXY_CONCURRENCY if proxy else 1
    NUM_SLOTS = 4

    prog = ChannelSyncProgress(
        channel_name="All Channels",
        slots=[None] * NUM_SLOTS,
        slot_count=concurrency,
    )
    _emit(progress_callback, prog)

    # --- Phase 1: fetch all channel video lists in parallel ---
    # Each channel is assigned a slot index so its fetch logs appear in the
    # correct quadrant immediately.  Fetches run concurrently; results are
    # collected before processing begins.
    channel_queues: dict[str, list[dict[str, Any]]] = {}
    channel_quality: dict[str, str] = {}

    auto_sync_channels = [ch for ch in channels_cfg if ch.get("auto_sync", True)]

    async def _fetch_one(ch: dict[str, Any], slot_idx: int) -> None:
        ch_name = ch["name"]
        ch_url = ch["url"]
        quality = QUALITY_MAP.get(ch.get("quality", "high"), "1080p")

        def _slog(msg: Any) -> None:
            if slot_log_callback:
                try:
                    slot_log_callback(slot_idx, msg)
                except Exception:
                    pass

        _slog(f"=== Fetching video list: {ch_name} ===")
        try:
            remote_videos = await fetch_channel_videos(ch_url, log_callback=_slog)
        except Exception as exc:
            _slog(f"ERROR fetching {ch_name}: {exc}")
            return

        library = load_library(ch_name)
        existing_ids = {v["video_id"] for v in library.get("videos", [])}
        new_videos = [v for v in remote_videos if v["video_id"] not in existing_ids]
        backfill = [
            v for v in library.get("videos", [])
            if not v.get("has_transcript") or not v.get("has_summary")
        ]
        to_process = new_videos + backfill

        for v in new_videos:
            upsert_video(ch_name, v)

        if to_process:
            channel_queues[ch_name] = to_process
            channel_quality[ch_name] = quality
            _slog(f"{ch_name}: {len(new_videos)} new, {len(backfill)} to backfill")
        else:
            _slog(f"{ch_name}: up to date")

    await asyncio.gather(*[
        _fetch_one(ch, i % NUM_SLOTS)
        for i, ch in enumerate(auto_sync_channels)
    ])

    prog.total = sum(len(q) for q in channel_queues.values())
    _emit(progress_callback, prog)

    if not channel_queues:
        _log(log_callback, "All channels are up to date.")
        prog.done = True
        _emit(progress_callback, prog)
        return

    # --- Phase 2: build interleaved work list ---
    # Each pass picks one video from each channel sorted by remaining count
    # (largest first).  This ensures every channel gets an initial slot and
    # the farthest-behind channel gets proportionally more throughput.
    work: list[tuple[str, dict[str, Any]]] = []
    queues_copy = {name: list(q) for name, q in channel_queues.items()}
    while any(queues_copy.values()):
        for ch_name in sorted(queues_copy, key=lambda c: -len(queues_copy[c])):
            if queues_copy[ch_name]:
                work.append((ch_name, queues_copy[ch_name].pop(0)))

    # --- Phase 3: process with concurrent slot workers ---
    semaphore = asyncio.Semaphore(concurrency)
    available_slots: list[int] = list(range(concurrency))

    async def _process_one(ch_name: str, video: dict[str, Any]) -> None:
        async with semaphore:
            slot_idx = available_slots.pop(0)

            def _slot_log(msg: Any) -> None:
                if slot_log_callback:
                    try:
                        slot_log_callback(slot_idx, msg)
                    except Exception:
                        pass

            quality = channel_quality[ch_name]
            try:
                await _process_video(
                    ch_name, video, quality, prog, slot_idx,
                    progress_callback, _slot_log,
                )
            except Exception as exc:
                msg = f"Failed to process {video.get('video_id')}: {exc}"
                logger.error(msg)
                _slot_log(f"ERROR: {msg}")
            finally:
                prog.slots[slot_idx] = None
                available_slots.append(slot_idx)
            prog.completed += 1
            _emit(progress_callback, prog)

    await asyncio.gather(*[_process_one(cn, v) for cn, v in work])

    for ch_name in channel_queues:
        mark_library_synced(ch_name)

    prog.done = True
    prog.slots = [None] * NUM_SLOTS
    _emit(progress_callback, prog)
    _log(
        log_callback,
        f"=== Sync complete: {prog.total} videos across {len(channel_queues)} channels ===",
    )
    logger.info("sync_all_channels complete: %d videos.", prog.total)
