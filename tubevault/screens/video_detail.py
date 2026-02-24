"""Video detail view — opens the HTML player in the browser."""

import logging
from typing import Any

from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import Footer, Header, Label, Static

from tubevault.core.html_player import open_video_player

logger = logging.getLogger(__name__)


class VideoDetailScreen(Screen):
    """Briefly shown while launching the browser-based HTML player.

    Automatically opens the video in the browser and shows key metadata.
    Press Escape to return to the library browser.
    """

    BINDINGS = [
        ("escape", "back", "Back"),
        ("enter", "open_player", "Open in Browser"),
    ]

    def __init__(self, channel_name: str, video: dict[str, Any], **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._channel_name = channel_name
        self._video = video

    def compose(self) -> ComposeResult:
        from tubevault.utils.helpers import format_duration

        video = self._video
        title = video.get("title", video["video_id"])
        date = video.get("upload_date", "")
        duration = format_duration(video.get("duration_seconds", 0))

        yield Header(show_clock=True)
        yield Static(title, id="detail_title")
        yield Label(f"Date: {date}   Duration: {duration}", id="detail_meta")
        yield Label("", id="detail_status")
        yield Label("[Enter] Open in browser   [Escape] Back", id="detail_hint")
        yield Footer()

    def on_mount(self) -> None:
        self._launch_player()

    def _launch_player(self) -> None:
        status = self.query_one("#detail_status", Label)
        try:
            open_video_player(self._channel_name, self._video)
            status.update("Opened in browser.")
        except Exception as exc:
            logger.error("Failed to open player: %s", exc)
            status.update(f"Error opening player: {exc}")

    def action_back(self) -> None:
        self.app.pop_screen()

    def action_open_player(self) -> None:
        self._launch_player()

    DEFAULT_CSS = """
    VideoDetailScreen {
        padding: 2 4;
    }
    #detail_title {
        text-style: bold;
        color: $accent;
        margin-bottom: 1;
    }
    #detail_meta {
        color: $text-muted;
        margin-bottom: 1;
    }
    #detail_status {
        color: $success;
        margin-bottom: 1;
    }
    #detail_hint {
        color: $text-muted;
    }
    """
