"""Editable ordered collection list with section headers and notes."""

from typing import Any

from rich.text import Text
from textual.app import ComposeResult
from textual.message import Message
from textual.widgets import ListItem, ListView, Label, Input
from textual.reactive import reactive


class CollectionList(ListView):
    """An editable ordered list supporting videos, section headers, and notes.

    Keybindings:
        Enter       — open video player
        Ctrl+Up / K — move item up
        Ctrl+Down / J — move item down
        h           — insert section header before current item
        n           — add/edit note on current video
        d / Delete  — remove item
    """

    class VideoSelected(Message):
        """Emitted when Enter is pressed on a video item."""

        def __init__(self, video_id: str) -> None:
            super().__init__()
            self.video_id = video_id

    class ItemMoved(Message):
        """Emitted after an item is moved."""

    class ItemRemoved(Message):
        """Emitted after an item is removed."""

    class HeaderInsertRequested(Message):
        """Emitted when user presses 'h' to insert a header."""

        def __init__(self, index: int) -> None:
            super().__init__()
            self.index = index

    class NoteEditRequested(Message):
        """Emitted when user presses 'n' to edit a note."""

        def __init__(self, video_id: str, current_note: str) -> None:
            super().__init__()
            self.video_id = video_id
            self.current_note = current_note

    def __init__(self, channel_name: str, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._channel_name = channel_name
        self._items: list[dict[str, Any]] = []
        self._video_map: dict[str, dict[str, Any]] = {}  # video_id -> library entry

    def set_items(
        self,
        items: list[dict[str, Any]],
        video_map: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        """Set the collection items.

        Args:
            items: Collection items list (video and section_header dicts).
            video_map: Map of video_id to library metadata for titles/dates.
        """
        self._items = items
        self._video_map = video_map or {}
        self._rebuild()

    def _rebuild(self) -> None:
        self.clear()
        for item in self._items:
            self.append(self._make_item(item))

    def _make_item(self, item: dict[str, Any]) -> ListItem:
        from tubevault.utils.helpers import format_duration

        if item.get("type") == "section_header":
            text = Text()
            text.append(f"── {item.get('text', '')} ──", style="bold yellow")
            return ListItem(Label(text))

        # Video item
        video_id = item.get("video_id", "")
        meta = self._video_map.get(video_id, {})
        title = meta.get("title", video_id)
        date = meta.get("upload_date", "")
        duration = format_duration(meta.get("duration_seconds", 0))
        note = item.get("note", "")

        max_title = 60
        display_title = title if len(title) <= max_title else title[: max_title - 1] + "…"

        text = Text()
        text.append(f"{display_title:<62}", style="white")
        text.append(f"  {date}  ", style="dim")
        text.append(f"{duration:>8}", style="cyan")
        if note:
            text.append(f"\n  ↳ {note}", style="italic dim green")

        return ListItem(Label(text))

    def on_key(self, event: Any) -> None:
        idx = self.index
        if idx is None:
            return

        if event.key == "enter":
            event.stop()
            item = self._items[idx]
            if item.get("type") == "video":
                self.post_message(self.VideoSelected(item["video_id"]))

        elif event.key in ("ctrl+up", "K"):
            event.stop()
            self._move(idx, -1)

        elif event.key in ("ctrl+down", "J"):
            event.stop()
            self._move(idx, 1)

        elif event.key == "h":
            event.stop()
            self.post_message(self.HeaderInsertRequested(idx))

        elif event.key == "n":
            event.stop()
            item = self._items[idx]
            if item.get("type") == "video":
                self.post_message(self.NoteEditRequested(item["video_id"], item.get("note", "")))

        elif event.key in ("d", "delete"):
            event.stop()
            self._remove(idx)

    def _move(self, index: int, direction: int) -> None:
        from tubevault.core.database import collection_move_item

        new_index = index + direction
        if not (0 <= new_index < len(self._items)):
            return
        collection_move_item(self._channel_name, index, direction)
        self._items[index], self._items[new_index] = self._items[new_index], self._items[index]
        self._rebuild()
        # Re-select moved item
        self.index = new_index
        self.post_message(self.ItemMoved())

    def _remove(self, index: int) -> None:
        from tubevault.core.database import collection_remove_item

        collection_remove_item(self._channel_name, index)
        self._items.pop(index)
        self._rebuild()
        self.post_message(self.ItemRemoved())

    def refresh_item(self, video_id: str, new_note: str) -> None:
        """Refresh a specific video item's note display.

        Args:
            video_id: The video ID to refresh.
            new_note: Updated note text.
        """
        for item in self._items:
            if item.get("video_id") == video_id:
                item["note"] = new_note
        self._rebuild()
