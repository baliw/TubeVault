"""yt-dlp wrapper for downloading videos, metadata, and thumbnails."""

import asyncio
import logging
from pathlib import Path
from typing import Any, Callable

import yt_dlp

from tubevault.core.database import video_dir
from tubevault.utils.helpers import ensure_dir

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
RETRY_BASE_DELAY = 2.0  # seconds; exponential backoff


def _ydl_opts_base(output_dir: Path, quality: str = "1080p") -> dict[str, Any]:
    """Build base yt-dlp options dict.

    Args:
        output_dir: Directory to write files into.
        quality: Maximum video quality (e.g. '1080p').

    Returns:
        yt-dlp options dict.
    """
    height = int(quality.rstrip("p")) if quality.endswith("p") else 1080
    return {
        "format": f"bestvideo[height<={height}][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<={height}]+bestaudio/best[height<={height}]/best",
        "merge_output_format": "mp4",
        "outtmpl": str(output_dir / "video.%(ext)s"),
        "quiet": True,
        "no_warnings": True,
        "ignoreerrors": False,
        "retries": MAX_RETRIES,
        "fragment_retries": MAX_RETRIES,
    }


def _videos_url(channel_url: str) -> str:
    """Ensure the channel URL points to the /videos tab.

    yt-dlp returns tabs (Videos/Shorts/Live) as nested playlists when given
    a bare channel URL. Pointing directly at /videos gives a flat video list.

    Args:
        channel_url: Raw channel URL entered by the user.

    Returns:
        URL guaranteed to target the Videos tab.
    """
    url = channel_url.rstrip("/")
    if url.endswith(("/videos", "/shorts", "/live", "/streams")):
        return url
    return url + "/videos"


async def fetch_channel_videos(channel_url: str) -> list[dict[str, Any]]:
    """Fetch the list of video metadata entries for a channel.

    Args:
        channel_url: YouTube channel URL.

    Returns:
        List of video info dicts.
    """
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _fetch_channel_videos_sync, channel_url)


def _fetch_channel_videos_sync(channel_url: str) -> list[dict[str, Any]]:
    """Synchronous implementation of channel video listing."""
    url = _videos_url(channel_url)
    logger.info("Fetching video list from %s", url)

    opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": True,
        "ignoreerrors": True,
    }

    results = []
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
        if not info:
            logger.warning("yt-dlp returned no info for %s", url)
            return []

        # entries must be consumed inside the with-block (lazy generator)
        for entry in info.get("entries") or []:
            if not entry:
                continue
            video_id = entry.get("id") or entry.get("url", "").split("?v=")[-1]
            if not video_id or entry.get("_type") == "playlist":
                continue
            results.append(
                {
                    "video_id": video_id,
                    "title": entry.get("title", ""),
                    "upload_date": _parse_date(entry.get("upload_date", "")),
                    "duration_seconds": entry.get("duration") or 0,
                    "description": entry.get("description", ""),
                    "thumbnail_url": entry.get("thumbnail", ""),
                    "has_video": False,
                    "has_transcript": False,
                    "has_summary": False,
                    "file_size_mb": 0.0,
                }
            )

    logger.info("Found %d videos for channel", len(results))
    return results


def _parse_date(raw: str) -> str:
    """Convert yt-dlp YYYYMMDD date to YYYY-MM-DD."""
    if len(raw) == 8:
        return f"{raw[:4]}-{raw[4:6]}-{raw[6:]}"
    return raw


async def download_video(
    channel_name: str,
    video_id: str,
    quality: str = "1080p",
    progress_callback: Callable[[float], None] | None = None,
) -> Path | None:
    """Download a YouTube video to the channel's video directory.

    Args:
        channel_name: Channel slug.
        video_id: YouTube video ID.
        quality: Maximum quality string (e.g. '1080p').
        progress_callback: Optional callable receiving progress 0.0–1.0.

    Returns:
        Path to the downloaded .mp4 file, or None on failure.
    """
    url = f"https://www.youtube.com/watch?v={video_id}"
    out_dir = video_dir(channel_name, video_id)
    ensure_dir(out_dir)

    loop = asyncio.get_running_loop()
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            result = await loop.run_in_executor(
                None,
                _download_sync,
                url,
                out_dir,
                quality,
                progress_callback,
            )
            if result:
                return result
        except Exception as exc:
            logger.warning(
                "Download attempt %d/%d failed for %s: %s",
                attempt, MAX_RETRIES, video_id, exc,
            )
            if attempt < MAX_RETRIES:
                await asyncio.sleep(RETRY_BASE_DELAY ** attempt)

    logger.error("All download attempts failed for %s", video_id)
    return None


def _download_sync(
    url: str,
    out_dir: Path,
    quality: str,
    progress_callback: Callable[[float], None] | None,
) -> Path | None:
    """Synchronous yt-dlp download."""
    opts = _ydl_opts_base(out_dir, quality)

    if progress_callback:
        def _hook(d: dict[str, Any]) -> None:
            if d["status"] == "downloading":
                total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                downloaded = d.get("downloaded_bytes") or 0
                if total:
                    progress_callback(downloaded / total)
            elif d["status"] == "finished":
                progress_callback(1.0)

        opts["progress_hooks"] = [_hook]

    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)

    if not info:
        return None

    # Prefer the explicit output path
    mp4 = out_dir / "video.mp4"
    if mp4.exists():
        return mp4

    # Fallback: any .mp4 yt-dlp wrote
    for f in out_dir.glob("*.mp4"):
        return f

    return None


async def fetch_video_metadata(video_id: str) -> dict[str, Any] | None:
    """Fetch detailed metadata for a single video (without downloading).

    Args:
        video_id: YouTube video ID.

    Returns:
        Metadata dict or None on failure.
    """
    url = f"https://www.youtube.com/watch?v={video_id}"
    opts = {"quiet": True, "no_warnings": True, "ignoreerrors": True}
    loop = asyncio.get_running_loop()
    try:
        info = await loop.run_in_executor(None, _extract_info, url, opts)
    except Exception as exc:
        logger.error("Failed to fetch metadata for %s: %s", video_id, exc)
        return None
    if not info:
        return None
    return {
        "video_id": video_id,
        "title": info.get("title", ""),
        "upload_date": _parse_date(info.get("upload_date", "")),
        "duration_seconds": info.get("duration") or 0,
        "description": info.get("description", ""),
        "thumbnail_url": info.get("thumbnail", ""),
    }


def _extract_info(url: str, opts: dict[str, Any]) -> dict[str, Any] | None:
    with yt_dlp.YoutubeDL(opts) as ydl:
        return ydl.extract_info(url, download=False)
