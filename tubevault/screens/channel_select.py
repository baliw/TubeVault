"""Channel selection startup screen."""

import logging
from typing import Any

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.screen import ModalScreen, Screen
from textual.widgets import Button, Header, Input, Label, ListItem, ListView, Static

from tubevault.core.config import add_channel, load_config, remove_channel

logger = logging.getLogger(__name__)


class _ChannelList(ListView):
    """ListView that moves focus to the action bar when UP is pressed at index 0."""

    def action_cursor_up(self) -> None:
        if self.index == 0 or self.index is None:
            # At the top — hand off focus to the first action button.
            self.screen.query_one("#btn_sync", Button).focus()
        else:
            super().action_cursor_up()


class ChannelSelectScreen(Screen):
    """Startup screen: list channels, add/remove, sync all.

    Navigation:
        ↑↓     — navigate channel list; ↑ at top moves to action bar
        ←→     — navigate action buttons
        ↓      — from action bar, return to channel list
        Enter  — select channel / activate button
        a      — add new channel
        r      — remove selected channel
        s      — synchronize all channels
        q / Escape — quit
    """

    TITLE = "TubeVault"

    BINDINGS = [
        Binding("escape", "app.quit", "Quit", priority=True),
        Binding("q", "app.quit", "Quit", priority=True),
        Binding("a", "add_channel", "Add Channel", priority=True),
        Binding("r", "remove_channel", "Remove Channel", priority=True),
        Binding("s", "sync_all", "Sync All", priority=True),
    ]

    class ChannelSelected(Message):
        """Emitted when a channel is chosen."""

        def __init__(self, channel: dict[str, Any]) -> None:
            super().__init__()
            self.channel = channel

    class SyncAllRequested(Message):
        """Emitted when the user requests a full sync."""

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Vertical(id="center_panel"):
            yield Static("TubeVault", id="app_title")
            with Horizontal(id="action_bar"):
                yield Button("Sync All", id="btn_sync")
                yield Button("Add", id="btn_add")
                yield Button("Remove", id="btn_remove")
                yield Button("Quit", id="btn_quit")
            yield _ChannelList(id="channel_list")
            yield Label("", id="status_label")

    def on_mount(self) -> None:
        self._refresh_list()

    def _refresh_list(self) -> None:
        config = load_config()
        lv = self.query_one("#channel_list", _ChannelList)
        lv.clear()
        channels = config.get("channels", [])
        for ch in channels:
            name = ch["name"]
            url = ch.get("url", "")
            lv.append(ListItem(Label(f"{name}  [dim]{url}[/dim]")))
        if not channels:
            lv.append(ListItem(Label("[dim]No channels yet — press [bold]a[/bold] to add one.[/dim]")))
        self.call_after_refresh(lv.focus)

    # ------------------------------------------------------------------ Key nav
    def on_key(self, event) -> None:
        """Handle arrow-key navigation between action buttons and channel list."""
        focused = self.focused
        if not isinstance(focused, Button):
            return
        buttons = list(self.query("#action_bar > Button"))
        if event.key == "down":
            event.stop()
            self.query_one("#channel_list", _ChannelList).focus()
        elif event.key == "right":
            event.stop()
            idx = buttons.index(focused)
            if idx < len(buttons) - 1:
                buttons[idx + 1].focus()
        elif event.key == "left":
            event.stop()
            idx = buttons.index(focused)
            if idx > 0:
                buttons[idx - 1].focus()

    # ------------------------------------------------------------------ Button actions
    def on_button_pressed(self, event: Button.Pressed) -> None:
        btn_id = event.button.id
        if btn_id == "btn_add":
            self.action_add_channel()
        elif btn_id == "btn_remove":
            self.action_remove_channel()
        elif btn_id == "btn_sync":
            self.action_sync_all()
        elif btn_id == "btn_quit":
            self.app.action_quit()

    # ------------------------------------------------------------------ ListView
    def on_list_view_selected(self, event: ListView.Selected) -> None:
        config = load_config()
        channels = config.get("channels", [])
        idx = self.query_one("#channel_list", _ChannelList).index
        if idx is not None and idx < len(channels):
            self.post_message(self.ChannelSelected(channels[idx]))

    # ------------------------------------------------------------------ Channel management
    def action_add_channel(self) -> None:
        self.app.push_screen(AddChannelScreen(), self._on_channel_added)

    def _on_channel_added(self, result: tuple[str, str] | None) -> None:
        if result:
            url, name = result
            add_channel(url, name)
            self._refresh_list()
            self.query_one("#status_label", Label).update(f"Added channel: {name}")

    def action_remove_channel(self) -> None:
        config = load_config()
        channels = config.get("channels", [])
        lv = self.query_one("#channel_list", _ChannelList)
        idx = lv.index
        if idx is None or idx >= len(channels):
            return
        ch = channels[idx]
        self.app.push_screen(
            ConfirmScreen(f"Remove channel '{ch['name']}'?"),
            lambda ok: self._do_remove(ok, ch["name"]),
        )

    def _do_remove(self, confirmed: bool, name: str) -> None:
        if confirmed:
            remove_channel(name)
            self._refresh_list()
            self.query_one("#status_label", Label).update(f"Removed channel: {name}")

    def action_sync_all(self) -> None:
        self.post_message(self.SyncAllRequested())

    DEFAULT_CSS = """
    ChannelSelectScreen {
        align: center middle;
    }
    #center_panel {
        width: 80;
        height: auto;
        align: center middle;
    }
    #app_title {
        text-align: center;
        text-style: bold;
        color: $accent;
        padding: 1 0;
        width: 100%;
    }
    #action_bar {
        width: 100%;
        height: auto;
        margin-bottom: 1;
        align: center middle;
    }
    #action_bar > Button {
        margin-right: 1;
        min-width: 12;
    }
    #channel_list {
        width: 100%;
        height: 20;
        border: solid $accent;
    }
    #status_label {
        text-align: center;
        color: $success;
        margin-top: 1;
        width: 100%;
    }
    """


class AddChannelScreen(ModalScreen):
    """Modal overlay for entering a new channel URL and name."""

    BINDINGS = [("escape", "cancel", "Cancel")]

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Static("Add Channel", id="modal_title")
            yield Label("YouTube channel URL or @handle:")
            yield Input(placeholder="https://www.youtube.com/@channel or @handle", id="url_input")
            yield Label("Display name (slug, no spaces):")
            yield Input(placeholder="my_channel", id="name_input")
            with Horizontal(id="btn_row"):
                yield Button("Add", id="add_btn", variant="primary")
                yield Button("Cancel", id="cancel_btn")

    def on_mount(self) -> None:
        self.query_one("#url_input", Input).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "add_btn":
            url = self.query_one("#url_input", Input).value.strip()
            name = self.query_one("#name_input", Input).value.strip().replace(" ", "_")
            if url and name:
                self.dismiss((url, name))
            else:
                self.query_one("#modal_title", Static).update("Add Channel — URL and name are required!")
        else:
            self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)

    DEFAULT_CSS = """
    AddChannelScreen {
        align: center middle;
    }
    #dialog {
        width: 72;
        height: auto;
        background: $panel;
        border: solid $accent;
        padding: 1 2;
    }
    #dialog > Label, #dialog > Input, #dialog > Static {
        margin-bottom: 1;
        width: 100%;
    }
    #modal_title {
        text-style: bold;
        color: $accent;
    }
    #btn_row {
        margin-top: 1;
        align: right middle;
        height: auto;
    }
    #btn_row > Button {
        margin-left: 1;
    }
    """


class ConfirmScreen(ModalScreen):
    """A simple yes/no confirmation modal overlay."""

    BINDINGS = [("escape", "no", "No")]

    def __init__(self, prompt: str, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._prompt = prompt

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Static(self._prompt, id="confirm_prompt")
            with Horizontal(id="btn_row"):
                yield Button("Yes", id="yes_btn", variant="error")
                yield Button("No", id="no_btn")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "yes_btn")

    def action_no(self) -> None:
        self.dismiss(False)

    DEFAULT_CSS = """
    ConfirmScreen {
        align: center middle;
    }
    #dialog {
        width: 52;
        height: auto;
        background: $panel;
        border: solid $accent;
        padding: 1 2;
    }
    #confirm_prompt {
        text-style: bold;
        text-align: center;
        margin-bottom: 1;
        width: 100%;
    }
    #btn_row {
        align: center middle;
        height: auto;
    }
    #btn_row > Button {
        margin-right: 1;
    }
    """
