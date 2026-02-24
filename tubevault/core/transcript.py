"""Transcript fetching and parsing with timestamps."""

import asyncio
import logging
from pathlib import Path
from typing import Any, Callable

from tubevault.core.database import video_dir
from tubevault.utils.helpers import ensure_dir

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
RETRY_BASE_DELAY = 2.0

LogCallback = Callable[[str], None]


async def fetch_transcript(
    channel_name: str,
    video_id: str,
    log_callback: LogCallback | None = None,
) -> list[dict[str, Any]] | None:
    """Fetch transcript for a video, trying youtube-transcript-api then yt-dlp.

    Args:
        channel_name: Channel slug (used for directory lookup).
        video_id: YouTube video ID.
        log_callback: Optional callback for status lines.

    Returns:
        List of segment dicts with ``text``, ``start``, ``duration`` keys,
        or None if unavailable.
    """
    if log_callback:
        log_callback(f"Fetching transcript for {video_id} via youtube-transcript-api")

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            segments = await asyncio.get_running_loop().run_in_executor(
                None, _fetch_via_transcript_api, video_id
            )
            if segments:
                if log_callback:
                    log_callback(f"Transcript fetched ({len(segments)} segments)")
                return segments
        except Exception as exc:
            msg = f"youtube-transcript-api attempt {attempt}/{MAX_RETRIES} failed for {video_id}: {exc}"
            logger.warning(msg)
            if log_callback:
                log_callback(msg)
            if attempt < MAX_RETRIES:
                await asyncio.sleep(RETRY_BASE_DELAY ** attempt)

    # Fallback: yt-dlp subtitle extraction
    msg = f"Falling back to yt-dlp subtitles for {video_id}"
    logger.info(msg)
    if log_callback:
        log_callback(msg)
    try:
        segments = await asyncio.get_running_loop().run_in_executor(
            None, _fetch_via_ytdlp, channel_name, video_id, log_callback
        )
        if segments:
            if log_callback:
                log_callback(f"Subtitles fetched via yt-dlp ({len(segments)} segments)")
            return segments
    except Exception as exc:
        msg = f"yt-dlp subtitle extraction failed for {video_id}: {exc}"
        logger.warning(msg)
        if log_callback:
            log_callback(msg)

    msg = f"No transcript available for {video_id}"
    logger.warning(msg)
    if log_callback:
        log_callback(msg)
    return None


def _fetch_via_transcript_api(video_id: str) -> list[dict[str, Any]] | None:
    """Use youtube-transcript-api to fetch auto-generated or manual captions."""
    try:
        from youtube_transcript_api import YouTubeTranscriptApi, TranscriptsDisabled, NoTranscriptFound
    except ImportError:
        logger.error("youtube-transcript-api not installed")
        return None

    try:
        segments = YouTubeTranscriptApi.get_transcript(video_id)
        return [{"text": s["text"], "start": s["start"], "duration": s.get("duration", 0)} for s in segments]
    except (TranscriptsDisabled, NoTranscriptFound):
        return None


def _fetch_via_ytdlp(
    channel_name: str,
    video_id: str,
    log_callback: LogCallback | None = None,
) -> list[dict[str, Any]] | None:
    """Use yt-dlp to download subtitles and parse them."""
    import yt_dlp
    from tubevault.core.downloader import _YdlLogger

    out_dir = video_dir(channel_name, video_id)
    ensure_dir(out_dir)
    url = f"https://www.youtube.com/watch?v={video_id}"

    opts: dict[str, Any] = {
        "skip_download": True,
        "writeautomaticsub": True,
        "writesubtitles": True,
        "subtitlesformat": "json3",
        "subtitleslangs": ["en"],
        "outtmpl": str(out_dir / "sub.%(ext)s"),
    }
    if log_callback:
        opts["logger"] = _YdlLogger(log_callback)
    else:
        opts["quiet"] = True
        opts["no_warnings"] = True

    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.download([url])

    # Parse the downloaded json3 subtitle file
    for sub_file in out_dir.glob("sub.*.json3"):
        return _parse_json3_subtitles(sub_file)

    # Try vtt format
    opts["subtitlesformat"] = "vtt"
    opts["outtmpl"] = str(out_dir / "sub2.%(ext)s")
    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.download([url])

    for sub_file in out_dir.glob("sub2.*.vtt"):
        return _parse_vtt_subtitles(sub_file)

    return None


def _parse_json3_subtitles(path: Path) -> list[dict[str, Any]]:
    """Parse yt-dlp json3 subtitle format."""
    import json

    with path.open() as f:
        data = json.load(f)

    segments = []
    for event in data.get("events", []):
        start_ms = event.get("tStartMs", 0)
        dur_ms = event.get("dDurationMs", 0)
        segs = event.get("segs", [])
        text = "".join(s.get("utf8", "") for s in segs).strip()
        if text and text != "\n":
            segments.append(
                {
                    "text": text,
                    "start": start_ms / 1000.0,
                    "duration": dur_ms / 1000.0,
                }
            )
    return segments


def _parse_vtt_subtitles(path: Path) -> list[dict[str, Any]]:
    """Parse WebVTT subtitle file into segments."""
    content = path.read_text(encoding="utf-8", errors="replace")
    segments = []
    lines = content.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if "-->" in line:
            parts = line.split("-->")
            start = _vtt_time_to_seconds(parts[0].strip())
            end = _vtt_time_to_seconds(parts[1].strip().split()[0])
            i += 1
            text_lines = []
            while i < len(lines) and lines[i].strip():
                text_lines.append(lines[i].strip())
                i += 1
            text = " ".join(text_lines)
            if text:
                segments.append({"text": text, "start": start, "duration": max(0, end - start)})
        else:
            i += 1
    return segments


def _vtt_time_to_seconds(time_str: str) -> float:
    """Convert VTT time string (HH:MM:SS.mmm or MM:SS.mmm) to seconds."""
    parts = time_str.split(":")
    if len(parts) == 3:
        h, m, s = parts
        return int(h) * 3600 + int(m) * 60 + float(s)
    elif len(parts) == 2:
        m, s = parts
        return int(m) * 60 + float(s)
    return float(time_str)


def transcript_to_text(segments: list[dict[str, Any]]) -> str:
    """Convert transcript segments to a plain text string with timestamps."""
    lines = []
    for seg in segments:
        start = seg.get("start", 0)
        minutes, secs = divmod(int(start), 60)
        lines.append(f"[{minutes:02d}:{secs:02d}] {seg['text']}")
    return "\n".join(lines)
