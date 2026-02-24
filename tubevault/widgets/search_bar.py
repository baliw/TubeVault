"""Search/filter bar widget."""

from typing import Any

from textual.app import ComposeResult
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Input


class SearchBar(Widget):
    """A search input bar that emits SearchChanged messages.

    Press '/' in parent to focus this bar. Press Escape to clear and unfocus.
    """

    DEFAULT_CSS = """
    SearchBar {
        height: 3;
        dock: bottom;
        display: none;
    }
    SearchBar.visible {
        display: block;
    }
    SearchBar Input {
        height: 3;
    }
    """

    class SearchChanged(Message):
        """Emitted when the search query changes."""

        def __init__(self, query: str) -> None:
            super().__init__()
            self.query = query

    class SearchClosed(Message):
        """Emitted when the search bar is closed."""

    def compose(self) -> ComposeResult:
        yield Input(placeholder="Search videos… (Escape to close)", id="search_input")

    def on_input_changed(self, event: Input.Changed) -> None:
        self.post_message(self.SearchChanged(event.value))

    def on_key(self, event: Any) -> None:
        if event.key == "escape":
            event.stop()
            self._close()

    def show(self) -> None:
        """Show the search bar and focus the input."""
        self.add_class("visible")
        self.query_one("#search_input", Input).focus()

    def _close(self) -> None:
        self.remove_class("visible")
        input_widget = self.query_one("#search_input", Input)
        input_widget.value = ""
        self.post_message(self.SearchClosed())
