"""Synchronization progress screen."""

import asyncio
import contextvars
import logging
import warnings
from typing import Any

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import Footer, Header, Label, RichLog, Static

from tubevault.core.sync import ChannelSyncProgress, sync_channel, sync_all_channels
from tubevault.widgets.progress_panel import ProgressPanel

logger = logging.getLogger(__name__)


class SyncScreen(Screen):
    """Full-screen sync progress display.

    The sync runs as an App-level worker so it survives this screen being
    popped.  Returning to this screen replays accumulated log lines and
    shows the latest progress state.
    """

    TITLE = "TubeVault"
    BINDINGS = [Binding("escape", "back", "Back (sync continues)", priority=True)]

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
        log = self.query_one("#output_log", RichLog)
        panel = self.query_one("#progress_panel", ProgressPanel)

        # Replay any log lines accumulated while this screen was not visible.
        for msg in self.app.sync_logs:
            log.write(Text(msg))

        # Show the latest progress snapshot.
        if self.app.sync_progress is not None:
            panel.update_progress(self.app.sync_progress)

        # Only start a new sync if one is not already running.
        if not self.app.sync_running:
            self.app.sync_logs.clear()
            self.app.sync_progress = None
            # Run the worker at the App level so it isn't cancelled when
            # this screen is popped.
            self.app.run_worker(self._run_sync(), exclusive=False)

    async def _run_sync(self) -> None:
        loop = asyncio.get_running_loop()
        # Capture context (includes Textual's active_app ContextVar) so
        # call_soon_threadsafe callbacks can access widgets safely.
        ctx = contextvars.copy_context()

        self.app.sync_running = True

        def _write_log(msg: str) -> None:
            self.app.sync_logs.append(msg)
            loop.call_soon_threadsafe(ctx.run, self._deliver_log, msg)

        def _progress_callback(prog: ChannelSyncProgress) -> None:
            self.app.sync_progress = prog
            loop.call_soon_threadsafe(ctx.run, self._deliver_progress, prog)

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
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
                        log_callback=_write_log,
                    )
                else:
                    await sync_all_channels(
                        progress_callback=_progress_callback,
                        log_callback=_write_log,
                    )
            except Exception as exc:
                logger.error("Sync error: %s", exc)
                err_msg = f"ERROR: {exc}"
                self.app.sync_logs.append(err_msg)
                loop.call_soon_threadsafe(ctx.run, self._deliver_log, err_msg)
            finally:
                self.app.sync_running = False

    def _deliver_log(self, msg: str) -> None:
        """Write a log line to whichever SyncScreen is currently on the stack."""
        for screen in self.app.screen_stack:
            if isinstance(screen, SyncScreen):
                try:
                    log = screen.query_one("#output_log", RichLog)
                    if log.is_mounted:
                        log.write(Text(msg))
                except Exception:
                    pass
                return

    def _deliver_progress(self, prog: ChannelSyncProgress) -> None:
        """Send a progress update to whichever SyncScreen is currently on the stack."""
        for screen in self.app.screen_stack:
            if isinstance(screen, SyncScreen):
                try:
                    panel = screen.query_one("#progress_panel", ProgressPanel)
                    if panel.is_mounted:
                        panel.update_progress(prog)
                except Exception:
                    pass
                return

    def action_back(self) -> None:
        self.app.pop_screen()

    DEFAULT_CSS = """
    SyncScreen {
        padding: 0 2;
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
