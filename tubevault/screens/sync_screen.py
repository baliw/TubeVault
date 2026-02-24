"""Synchronization progress screen."""

import asyncio
import contextlib
import logging
import os
import warnings
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

    async def _run_sync(self) -> None:
        # Cache widget references and event loop NOW (main async context).
        # Callbacks may be invoked from executor threads, so we must not
        # call query_one() or capture asyncio.get_running_loop() from there.
        panel: ProgressPanel = self.query_one("#progress_panel", ProgressPanel)
        log: RichLog = self.query_one("#output_log", RichLog)
        loop = asyncio.get_running_loop()

        def _write_log(msg: str) -> None:
            if log.is_mounted:
                loop.call_soon_threadsafe(log.write, Text(msg))

        def _progress_callback(prog: ChannelSyncProgress) -> None:
            if panel.is_mounted:
                loop.call_soon_threadsafe(panel.update_progress, prog)

        # Suppress all output that could corrupt the Textual terminal:
        #
        # Layer 1 — Python level: contextlib.redirect_* covers any Python
        #   code that writes via sys.stdout / sys.stderr.
        #
        # Layer 2 — OS fd level: os.dup2 covers native subprocesses (ffmpeg,
        #   etc.) that yt-dlp forks.  Those processes inherit file descriptor
        #   2 (stderr) from the parent and write directly at the OS level,
        #   completely bypassing Python's sys.stderr object.  We save fd 2,
        #   point it at /dev/null for the duration of the sync, then restore.
        #
        # We intentionally leave fd 1 (stdout) alone because Textual's
        # terminal driver writes there for screen rendering.
        saved_stderr_fd = os.dup(2)
        devnull_fd = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull_fd, 2)
        os.close(devnull_fd)

        devnull = open(os.devnull, "w")
        try:
            with (
                contextlib.redirect_stdout(devnull),
                contextlib.redirect_stderr(devnull),
                warnings.catch_warnings(),
            ):
                warnings.simplefilter("ignore")
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
            loop.call_soon_threadsafe(log.write, Text(f"ERROR: {exc}"))
        finally:
            devnull.close()
            # Restore stderr fd so logging works normally after sync.
            os.dup2(saved_stderr_fd, 2)
            os.close(saved_stderr_fd)

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
