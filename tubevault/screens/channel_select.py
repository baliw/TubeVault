"""Channel selection startup screen."""

import logging
from typing import Any

from textual.app import ComposeResult
from textual.message import Message
from textual.screen import Screen
from textual.containers import Vertical
from textual.widgets import Button, Footer, Header, Input, Label, ListItem, ListView, Static

from tubevault.core.config import add_channel, load_config, remove_channel

logger = logging.getLogger(__name__)


class ChannelSelectScreen(Screen):
    """Startup screen: list channels, add/remove, sync all.

    Keybindings:
        ↑↓     — navigate channel list
        Enter  — select channel
        a      — add new channel
        r      — remove selected channel
        s      — synchronize all channels
        q / Escape — quit
    """

    TITLE = "TubeVault"

    BINDINGS = [
        ("escape", "app.quit", "Quit"),
        ("q", "app.quit", "Quit"),
        ("a", "add_channel", "Add Channel"),
        ("r", "remove_channel", "Remove Channel"),
        ("s", "sync_all", "Sync All"),
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
            yield Static("Select a channel  [a] Add  [r] Remove  [s] Sync All  [q] Quit", id="instructions")
            yield ListView(id="channel_list")
            yield Label("", id="status_label")
        yield Footer()

    def on_mount(self) -> None:
        self._refresh_list()

    def _refresh_list(self) -> None:
        config = load_config()
        lv: ListView = self.query_one("#channel_list", ListView)
        lv.clear()
        channels = config.get("channels", [])
        for ch in channels:
            name = ch["name"]
            url = ch.get("url", "")
            lv.append(ListItem(Label(f"{name}  [dim]{url}[/dim]"), id=f"ch_{name}"))
        if not channels:
            lv.append(ListItem(Label("[dim]No channels configured. Press [bold]a[/bold] to add one.[/dim]")))
        lv.focus()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        config = load_config()
        channels = config.get("channels", [])
        idx = self.query_one("#channel_list", ListView).index
        if idx is not None and idx < len(channels):
            self.post_message(self.ChannelSelected(channels[idx]))

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
        lv = self.query_one("#channel_list", ListView)
        idx = lv.index
        if idx is None or idx >= len(channels):
            return
        ch = channels[idx]
        self.app.push_screen(ConfirmScreen(f"Remove channel '{ch['name']}'?"), lambda ok: self._do_remove(ok, ch["name"]))

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
    #instructions {
        text-align: center;
        color: $text-muted;
        margin-bottom: 1;
        width: 100%;
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


class AddChannelScreen(Screen):
    """Modal screen for entering a new channel URL and name."""

    BINDINGS = [("escape", "cancel", "Cancel")]

    def compose(self) -> ComposeResult:
        yield Static("Add Channel", id="modal_title")
        yield Label("YouTube channel URL or @handle:")
        yield Input(placeholder="https://www.youtube.com/@channel or @handle", id="url_input")
        yield Label("Display name (slug, no spaces):")
        yield Input(placeholder="my_channel", id="name_input")
        yield Button("Add", id="add_btn", variant="primary")
        yield Button("Cancel", id="cancel_btn")

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
    AddChannelScreen > * {
        width: 70;
        margin-bottom: 1;
    }
    #modal_title {
        text-style: bold;
        color: $accent;
    }
    """


class ConfirmScreen(Screen):
    """A simple yes/no confirmation modal."""

    BINDINGS = [("escape", "no", "No")]

    def __init__(self, prompt: str, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._prompt = prompt

    def compose(self) -> ComposeResult:
        yield Static(self._prompt, id="confirm_prompt")
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
    ConfirmScreen > * {
        width: 50;
        margin-bottom: 1;
    }
    #confirm_prompt {
        text-style: bold;
        text-align: center;
    }
    """
