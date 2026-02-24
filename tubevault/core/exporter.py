"""Export video summaries to Markdown files."""

import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from tubevault.core.database import load_library, load_summary
from tubevault.core.summarizer import generate_master_summary
from tubevault.utils.helpers import format_duration, format_timestamp

logger = logging.getLogger(__name__)


def _video_to_markdown(video: dict[str, Any], summary: dict[str, Any]) -> str:
    """Render a single video entry as Markdown.

    Args:
        video: Library video entry dict.
        summary: Summary dict for the video.

    Returns:
        Markdown string for this video.
    """
    title = video.get("title", video["video_id"])
    upload_date = video.get("upload_date", "")
    duration = format_duration(video.get("duration_seconds", 0))
    summary_text = summary.get("summary_text", "")
    main_points = summary.get("main_points", [])

    lines = [
        f"## {title}",
        f"**Date:** {upload_date} | **Duration:** {duration}",
        "",
        summary_text,
        "",
        "### Key Points",
    ]
    for point in main_points:
        ts = format_timestamp(point.get("start_time_seconds", 0))
        lines.append(f"- **[{ts}]** — {point.get('point', '')}")
        if point.get("detail"):
            lines.append(f"  {point['detail']}")
    lines.append("")
    lines.append("---")
    return "\n".join(lines)


async def export_channel(
    channel_name: str,
    output_path: Path,
    include_master_summary: bool = False,
) -> None:
    """Export all summaries for a channel to a single Markdown file.

    Args:
        channel_name: Channel slug.
        output_path: Destination .md file path.
        include_master_summary: If True, prepend a master AI synthesis.
    """
    library = load_library(channel_name)
    videos = sorted(
        library.get("videos", []),
        key=lambda v: v.get("upload_date", ""),
        reverse=True,
    )

    video_sections: list[str] = []
    for video in videos:
        if not video.get("has_summary"):
            continue
        summary = load_summary(channel_name, video["video_id"])
        if not summary:
            continue
        video_sections.append(_video_to_markdown(video, summary))

    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    header = f"# TubeVault Summary Export: {channel_name}\nGenerated: {now}\n\n---\n"
    body = "\n\n".join(video_sections)
    full_content = header + "\n" + body

    if include_master_summary and video_sections:
        logger.info("Generating master summary for %s…", channel_name)
        master = await generate_master_summary(body)
        if master:
            master_section = f"# Master Summary\n\n{master}\n\n---\n\n"
            full_content = master_section + full_content

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(full_content, encoding="utf-8")
    logger.info("Exported %d summaries to %s", len(video_sections), output_path)
