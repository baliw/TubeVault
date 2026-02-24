"""Synchronization progress screen."""

import logging
from typing import Any

from rich.text import Text
from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import Footer, Header, Label, RichLog, Static

from tubevault.core.sync import ChannelSyncProgress, sync_channel, sync_all_channels
from tubevault.widgets.progress_panel import ProgressPanel

logger = logging.getLogger(__name__)


class SyncScreen(Screen):
    """Full-screen sync progress display.

    The sync runs in a background worker; pressing Escape returns to the
    previous screen while sync continues.
    """

    TITLE = "TubeVault"
    BINDINGS = [("escape", "back", "Back (sync continues)")]

    def __init__(
        self,
        channel_name: str | None = None,
        channel_url: str | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._channel_name = channel_name
        self._channel_url = channel_url

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Label("Press Escape to return; sync continues in background.", id="sync_hint")
        yield ProgressPanel(channel_name=self._channel_name or "", id="progress_panel")
        yield RichLog(
            highlight=False,
            markup=False,
            wrap=True,
            id="output_log",
        )
        yield Footer()

    def on_mount(self) -> None:
        self.run_worker(self._run_sync(), exclusive=False)

    def _write_log(self, msg: str) -> None:
        """Thread-safe write to the output log widget.

        Args:
            msg: Plain text message to append.
        """
        self.call_from_thread(self.query_one("#output_log", RichLog).write, Text(msg))

    async def _run_sync(self) -> None:
        panel: ProgressPanel = self.query_one("#progress_panel", ProgressPanel)

        def _progress_callback(prog: ChannelSyncProgress) -> None:
            self.call_from_thread(panel.update_progress, prog)

        try:
            if self._channel_name and self._channel_url:
                from tubevault.core.config import load_config
                config = load_config()
                quality = config.get("download_quality", "1080p")
                max_concurrent = config.get("max_concurrent_downloads", 2)
                await sync_channel(
                    channel_name=self._channel_name,
                    channel_url=self._channel_url,
                    quality=quality,
                    max_concurrent=max_concurrent,
                    progress_callback=_progress_callback,
                    log_callback=self._write_log,
                )
            else:
                await sync_all_channels(
                    progress_callback=_progress_callback,
                    log_callback=self._write_log,
                )
        except Exception as exc:
            logger.error("Sync error: %s", exc)
            self._write_log(f"ERROR: {exc}")

    def action_back(self) -> None:
        self.app.pop_screen()

    DEFAULT_CSS = """
    SyncScreen {
        padding: 1 2;
        layout: vertical;
    }
    #sync_hint {
        color: $text-muted;
        margin-bottom: 1;
    }
    #progress_panel {
        width: 100%;
        height: auto;
        margin-bottom: 1;
    }
    #output_log {
        width: 100%;
        height: 1fr;
        border: solid $panel-lighten-2;
        background: $panel;
        padding: 0 1;
    }
    """
