"""Textual App root for TubeVault."""

import logging
import os
from typing import Any

from textual.app import App, ComposeResult
from textual.binding import Binding

from tubevault.core.config import load_config
from tubevault.core.html_player import cleanup_temp_files
from tubevault.screens.channel_select import ChannelSelectScreen
from tubevault.screens.library_browser import LibraryBrowserScreen
from tubevault.screens.sync_screen import SyncScreen

logger = logging.getLogger(__name__)

APP_CSS = """
Screen {
    background: $background;
}
HeaderIcon {
    display: none;
}
HeaderTitle {
    content-align: left middle;
    padding: 0 1;
}
"""


class TubeVaultApp(App):
    """TubeVault — YouTube video library manager with AI summaries."""

    TITLE = "TubeVault"
    ENABLE_COMMAND_PALETTE = False
    CSS = APP_CSS

    BINDINGS = [
        Binding("ctrl+q", "quit", "Quit", show=False, priority=True),
    ]

    # ------------------------------------------------------------------ Sync state
    # These survive SyncScreen being popped so progress can be replayed
    # when the user navigates back to the sync view.
    sync_running: bool = False
    sync_slot_logs: list[list] = [[], [], [], []]  # per-slot log replay buffers
    sync_progress: Any = None  # ChannelSyncProgress | None

    def on_mount(self) -> None:
        self.push_screen(ChannelSelectScreen())

    # ------------------------------------------------------------------ First-run
    def _ensure_first_run(self) -> None:
        """Initialize ~/TubeVault/ and prompt for first channel if needed."""
        from tubevault.utils.helpers import tubevault_root
        tubevault_root()  # ensures dir exists

    # ------------------------------------------------------------------ Screen routing
    def on_channel_select_screen_channel_selected(
        self, event: ChannelSelectScreen.ChannelSelected
    ) -> None:
        self.push_screen(LibraryBrowserScreen(event.channel))

    def on_channel_select_screen_sync_all_requested(
        self, _: ChannelSelectScreen.SyncAllRequested
    ) -> None:
        self.push_screen(SyncScreen())

    def on_library_browser_screen_sync_channel_requested(
        self, event: LibraryBrowserScreen.SyncChannelRequested
    ) -> None:
        self.push_screen(
            SyncScreen(
                channel_name=event.channel_name,
                channel_url=event.channel_url,
            )
        )

    # ------------------------------------------------------------------ Cleanup
    def action_quit(self) -> None:
        # Check sync_running here, before Textual cancels workers (which sets
        # it to False in the worker's finally block).  os._exit bypasses
        # Python's atexit handlers — specifically concurrent.futures'
        # shutdown(wait=True) which would otherwise stall the terminal for the
        # duration of whatever yt-dlp download is in flight.
        if self.sync_running:
            cleanup_temp_files()
            import sys
            sys.stdout.write("\x1b[?25h")  # re-enable cursor before hard exit
            sys.stdout.flush()
            os._exit(0)
        self.exit()

    def on_unmount(self) -> None:
        import sys
        sys.stdout.write("\x1b[?25h")
        sys.stdout.flush()
        cleanup_temp_files()
