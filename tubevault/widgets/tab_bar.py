"""Top tab bar widget: 'All' | 'Collection'."""

from typing import Any

from textual.app import ComposeResult
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Label


TABS = ["All", "Collection"]


class TabBar(Widget):
    """A simple top tab bar with 'All' and 'Collection' tabs.

    Emits TabChanged messages when the active tab changes.
    Keybindings: Tab key (handled by parent screen via ContentSwitcher).
    """

    DEFAULT_CSS = """
    TabBar {
        height: 3;
        dock: top;
        layout: horizontal;
        background: $panel;
        padding: 0 1;
    }
    TabBar .tab {
        padding: 0 2;
        height: 3;
        content-align: center middle;
        color: $text-muted;
    }
    TabBar .tab.active {
        color: $text;
        background: $boost;
        text-style: bold;
        border-bottom: tall $accent;
    }
    """

    class TabChanged(Message):
        """Emitted when the active tab changes."""

        def __init__(self, tab: str) -> None:
            super().__init__()
            self.tab = tab

    active_tab: reactive[str] = reactive("All", init=False)

    def compose(self) -> ComposeResult:
        for tab in TABS:
            classes = "tab active" if tab == self.active_tab else "tab"
            yield Label(tab, id=f"tab_{tab.lower()}", classes=classes)

    def watch_active_tab(self, new_tab: str) -> None:
        for tab in TABS:
            label = self.query_one(f"#tab_{tab.lower()}", Label)
            if tab == new_tab:
                label.add_class("active")
            else:
                label.remove_class("active")

    def switch_tab(self) -> None:
        """Toggle between All and Collection tabs."""
        current_index = TABS.index(self.active_tab)
        new_tab = TABS[(current_index + 1) % len(TABS)]
        self.active_tab = new_tab
        self.post_message(self.TabChanged(new_tab))

    def set_tab(self, tab: str) -> None:
        """Set the active tab by name.

        Args:
            tab: Tab name ('All' or 'Collection').
        """
        if tab in TABS:
            self.active_tab = tab
            self.post_message(self.TabChanged(tab))
