"""Synchronization progress screen."""

import asyncio
import logging
from typing import Any

from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import Footer, Header, Label, Static

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
        yield Static("Synchronizing…", id="sync_title")
        yield Label("Press Escape to return; sync continues in background.", id="sync_hint")
        yield ProgressPanel(channel_name=self._channel_name or "", id="progress_panel")
        yield Footer()

    def on_mount(self) -> None:
        self.run_worker(self._run_sync(), exclusive=False)

    async def _run_sync(self) -> None:
        panel: ProgressPanel = self.query_one("#progress_panel", ProgressPanel)

        def _callback(prog: ChannelSyncProgress) -> None:
            # Schedule UI update on main thread
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
                    progress_callback=_callback,
                )
            else:
                await sync_all_channels(progress_callback=_callback)
        except Exception as exc:
            logger.error("Sync error: %s", exc)
            self.call_from_thread(
                self.query_one("#sync_title", Static).update,
                f"Sync error: {exc}",
            )

    def action_back(self) -> None:
        self.app.pop_screen()

    DEFAULT_CSS = """
    SyncScreen {
        padding: 1 2;
    }
    #sync_title {
        text-style: bold;
        color: $accent;
        margin-bottom: 1;
    }
    #sync_hint {
        color: $text-muted;
        margin-bottom: 2;
    }
    #progress_panel {
        width: 100%;
    }
    """
