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

from tubevault.core.config import load_config
from tubevault.core.sync import (
    INTER_REQUEST_DELAY,
    ChannelSyncProgress, sync_channel, sync_all_channels,
)
from tubevault.utils.helpers import load_proxy_url
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
        yield Label("", id="sync_config_label")
        yield ProgressPanel(channel_name=self._channel_name or "", id="progress_panel")
        yield Label("", id="countdown_label")
        yield RichLog(
            highlight=False,
            markup=False,
            wrap=True,
            id="output_log",
        )
        yield Footer()

    def on_mount(self) -> None:
        self._populate_config_label()
        log = self.query_one("#output_log", RichLog)
        panel = self.query_one("#progress_panel", ProgressPanel)

        # Replay any log lines accumulated while this screen was not visible.
        for msg in self.app.sync_logs:
            log.write(msg if isinstance(msg, Text) else Text(msg))

        # Show the latest progress snapshot.
        if self.app.sync_progress is not None:
            panel.update_progress(self.app.sync_progress)
            lbl = self.query_one("#countdown_label", Label)
            p = self.app.sync_progress
            if p.retry_countdown > 0:
                style = "bold orange1" if p.retry_message.startswith("⏳") else "dim cyan"
                lbl.update(Text(p.retry_message, style=style))

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

        def _write_log(msg: Any) -> None:
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

    def _deliver_log(self, msg: Any) -> None:
        """Write a log line to whichever SyncScreen is currently on the stack."""
        for screen in self.app.screen_stack:
            if isinstance(screen, SyncScreen):
                try:
                    log = screen.query_one("#output_log", RichLog)
                    if log.is_mounted:
                        log.write(msg if isinstance(msg, Text) else Text(msg))
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
                    lbl = screen.query_one("#countdown_label", Label)
                    if lbl.is_mounted:
                        if prog.retry_countdown > 0:
                            style = "bold orange1" if prog.retry_message.startswith("⏳") else "dim cyan"
                            lbl.update(Text(prog.retry_message, style=style))
                        else:
                            lbl.update("")
                except Exception:
                    pass
                return

    def _populate_config_label(self) -> None:
        proxy_url = load_proxy_url()
        config = load_config()
        max_concurrent = config.get("max_concurrent_downloads", 2)

        if proxy_url:
            from urllib.parse import urlparse
            p = urlparse(proxy_url)
            proxy_display = f"{p.hostname}:{p.port}"
            threads_display = str(max_concurrent)
            spacing_display = "none"
        else:
            proxy_display = "none"
            threads_display = "1"
            spacing_display = f"{INTER_REQUEST_DELAY}s"

        t = Text()
        t.append("Proxy: ", style="dim")
        t.append(proxy_display, style="cyan")
        t.append("   Threads: ", style="dim")
        t.append(threads_display, style="cyan")
        t.append("   Request spacing: ", style="dim")
        t.append(spacing_display, style="cyan")
        self.query_one("#sync_config_label", Label).update(t)

    def action_back(self) -> None:
        self.app.pop_screen()

    DEFAULT_CSS = """
    SyncScreen {
        padding: 0 2;
        layout: vertical;
    }
    #sync_hint {
        color: $text-muted;
        margin-bottom: 0;
    }
    #sync_config_label {
        width: 100%;
        height: 1;
        margin-bottom: 1;
    }
    #progress_panel {
        width: 100%;
        height: auto;
        margin-bottom: 0;
    }
    #countdown_label {
        width: 100%;
        height: 1;
        margin-bottom: 0;
    }
    #output_log {
        width: 100%;
        height: 1fr;
        border: solid $panel-lighten-2;
        background: $panel;
        padding: 0 1;
    }
    """
