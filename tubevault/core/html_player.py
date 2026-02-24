"""Generate a temporary HTML video player page and open it in the browser."""

import logging
import os
import tempfile
import webbrowser
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader

from tubevault.core.database import load_summary, video_dir
from tubevault.utils.helpers import format_timestamp

logger = logging.getLogger(__name__)

_TEMPLATE_DIR = Path(__file__).parent.parent / "templates"

_TEMP_FILES: list[Path] = []


def open_video_player(channel_name: str, video: dict[str, Any]) -> None:
    """Generate an HTML player page for a video and open it in the browser.

    Args:
        channel_name: Channel slug.
        video: Library video entry dict.
    """
    video_id = video["video_id"]
    vdir = video_dir(channel_name, video_id)
    video_file = vdir / "video.mp4"
    summary = load_summary(channel_name, video_id) or {}

    # Format main points for template
    main_points = []
    for point in summary.get("main_points", []):
        main_points.append(
            {
                **point,
                "timestamp": format_timestamp(point.get("start_time_seconds", 0)),
            }
        )

    env = Environment(loader=FileSystemLoader(str(_TEMPLATE_DIR)), autoescape=True)
    template = env.get_template("player.html")
    html = template.render(
        title=video.get("title", video_id),
        video_uri=video_file.as_uri() if video_file.exists() else "",
        summary_text=summary.get("summary_text", ""),
        main_points=main_points,
        has_video=video_file.exists(),
    )

    tmp = Path(tempfile.mktemp(suffix=".html", prefix="tubevault_player_"))
    tmp.write_text(html, encoding="utf-8")
    _TEMP_FILES.append(tmp)

    webbrowser.open(tmp.as_uri())
    logger.info("Opened player for %s at %s", video_id, tmp)


def cleanup_temp_files() -> None:
    """Remove all temporary HTML player files created in this session."""
    for path in _TEMP_FILES:
        try:
            path.unlink(missing_ok=True)
        except OSError as exc:
            logger.warning("Failed to remove temp file %s: %s", path, exc)
    _TEMP_FILES.clear()
