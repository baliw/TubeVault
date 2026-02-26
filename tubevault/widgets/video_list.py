"""Scrollable video list widget for the All tab."""

from typing import Any

from rich.text import Text
from textual.app import ComposeResult
from textual.message import Message
from textual.reactive import reactive
from textual.widgets import ListItem, ListView, Label


STATUS_ICONS = {
    "video": ("✓", "✗"),
    "transcript": ("✓", "✗"),
    "summary": ("✓", "✗"),
}


class VideoList(ListView):
    """A scrollable list of videos with sync status icons.

    Displays title, upload date, duration, and status icons for each video.
    """

    class VideoSelected(Message):
        """Emitted when the user presses Enter on a video."""

        def __init__(self, video: dict[str, Any]) -> None:
            super().__init__()
            self.video = video

    class VideoAddToCollection(Message):
        """Emitted when the user presses 'a' on a video."""

        def __init__(self, video: dict[str, Any]) -> None:
            super().__init__()
            self.video = video

    class SyncRequested(Message):
        """Emitted when the user presses 's'."""

    videos: reactive[list[dict[str, Any]]] = reactive([], layout=True)

    def __init__(self, videos: list[dict[str, Any]] | None = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._videos: list[dict[str, Any]] = videos or []
        self._current_filter: str = ""

    def on_mount(self) -> None:
        self._rebuild()

    def set_videos(self, videos: list[dict[str, Any]]) -> None:
        """Replace the displayed video list.

        Args:
            videos: New list of video entry dicts.
        """
        self._videos = list(videos)
        self._rebuild()

    def append_videos(self, videos: list[dict[str, Any]]) -> None:
        """Append additional videos to the bottom of the list.

        Respects any active filter — only appends entries that match.

        Args:
            videos: Video entries to add (already sorted in display order).
        """
        self._videos.extend(videos)
        q = self._current_filter.lower()
        for video in videos:
            if not q or q in video.get("title", "").lower():
                self.append(self._make_item(video))

    def _rebuild(self) -> None:
        """Clear and repopulate the list items, respecting active filter."""
        self.clear()
        q = self._current_filter.lower()
        for video in self._videos:
            if not q or q in video.get("title", "").lower():
                self.append(self._make_item(video))

    def _make_item(self, video: dict[str, Any]) -> ListItem:
        from tubevault.utils.helpers import format_duration

        title = video.get("title", video["video_id"])
        date = video.get("upload_date", "")
        duration = format_duration(video.get("duration_seconds", 0))

        v_icon = "✓" if video.get("has_video") else "·"
        t_icon = "✓" if video.get("has_transcript") else "·"
        s_icon = "✓" if video.get("has_summary") else "·"

        # Truncate long titles for display
        max_title = 60
        display_title = title if len(title) <= max_title else title[: max_title - 1] + "…"

        text = Text()
        text.append(f"{display_title:<62}", style="bold white")
        text.append(f"  {date}  ", style="dim")
        text.append(f"{duration:>8}  ", style="cyan")
        text.append(f"V{v_icon} ", style="green" if video.get("has_video") else "red")
        text.append(f"T{t_icon} ", style="green" if video.get("has_transcript") else "red")
        text.append(f"S{s_icon}", style="green" if video.get("has_summary") else "red")

        return ListItem(Label(text), id=f"v_{video['video_id']}")

    def on_key(self, event: Any) -> None:
        if not self._videos:
            return
        idx = self.index
        if idx is None:
            return
        if event.key == "enter":
            event.stop()
            self.post_message(self.VideoSelected(self._videos[idx]))
        elif event.key == "a":
            event.stop()
            self.post_message(self.VideoAddToCollection(self._videos[idx]))
        elif event.key == "s":
            event.stop()
            self.post_message(self.SyncRequested())

    def filter(self, query: str) -> None:
        """Filter displayed videos by title substring (case-insensitive).

        Args:
            query: Search string.
        """
        self._current_filter = query
        self._rebuild()
