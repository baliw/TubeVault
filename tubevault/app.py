"""Textual App root for TubeVault."""

import logging
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
"""


class TubeVaultApp(App):
    """TubeVault — YouTube video library manager with AI summaries."""

    TITLE = "TubeVault"
    ENABLE_COMMAND_PALETTE = False
    CSS = APP_CSS

    BINDINGS = [
        Binding("ctrl+q", "quit", "Quit", show=False, priority=True),
    ]

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
    def on_unmount(self) -> None:
        cleanup_temp_files()
