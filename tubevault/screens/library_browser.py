"""Main library browser screen with All and Collection tabs."""

import logging
from typing import Any

from textual.app import ComposeResult
from textual.binding import Binding
from textual.message import Message
from textual.screen import Screen
from textual.widgets import ContentSwitcher, Footer, Header, Input, Label, Static

from tubevault.core.database import (
    collection_add_video,
    collection_insert_header,
    collection_set_note,
    load_collection,
    load_library,
)
from tubevault.widgets.collection_list import CollectionList
from tubevault.widgets.search_bar import SearchBar
from tubevault.widgets.tab_bar import TabBar
from tubevault.widgets.video_list import VideoList

logger = logging.getLogger(__name__)


class LibraryBrowserScreen(Screen):
    """Main screen: two-tab browser for a channel's video library.

    Tabs:
        All        — all videos, sorted by upload date newest-first
        Collection — user-curated ordered list
    """

    TITLE = "TubeVault"

    BINDINGS = [
        Binding("escape", "back", "Back", priority=True),
        Binding("q", "app.quit", "Quit", priority=True),
        Binding("tab", "switch_tab", "Switch Tab", priority=True),
        Binding("/", "show_search", "Search", priority=True),
    ]

    class SyncChannelRequested(Message):
        """Emitted when the user requests a channel sync."""

        def __init__(self, channel_name: str, channel_url: str) -> None:
            super().__init__()
            self.channel_name = channel_name
            self.channel_url = channel_url

    def __init__(self, channel: dict[str, Any], **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._channel = channel
        self._channel_name: str = channel["name"]
        self._channel_url: str = channel.get("url", "")
        self._all_videos: list[dict[str, Any]] = []

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield TabBar(id="tab_bar")
        yield ContentSwitcher(
            VideoList(id="all_list"),
            CollectionList(self._channel_name, id="collection_list"),
            initial="all_list",
            id="content_switcher",
        )
        yield SearchBar(id="search_bar")
        yield Label("", id="status_label")
        yield Footer()

    def on_mount(self) -> None:
        self._load_all()
        self._load_collection()

    def _load_all(self) -> None:
        library = load_library(self._channel_name)
        videos = sorted(
            library.get("videos", []),
            key=lambda v: v.get("upload_date", ""),
            reverse=True,
        )
        self._all_videos = videos
        self.query_one("#all_list", VideoList).set_videos(videos)

    def _load_collection(self) -> None:
        collection = load_collection(self._channel_name)
        library = load_library(self._channel_name)
        video_map = {v["video_id"]: v for v in library.get("videos", [])}
        self.query_one("#collection_list", CollectionList).set_items(
            collection.get("items", []), video_map
        )

    # ------------------------------------------------------------------ Tab
    def action_switch_tab(self) -> None:
        self.query_one("#tab_bar", TabBar).switch_tab()

    def on_tab_bar_tab_changed(self, event: TabBar.TabChanged) -> None:
        switcher = self.query_one("#content_switcher", ContentSwitcher)
        if event.tab == "All":
            switcher.current = "all_list"
        else:
            switcher.current = "collection_list"
            self._load_collection()

    # ------------------------------------------------------------------ VideoList events
    def on_video_list_video_selected(self, event: VideoList.VideoSelected) -> None:
        self._open_video(event.video)

    def on_video_list_video_add_to_collection(self, event: VideoList.VideoAddToCollection) -> None:
        video_id = event.video["video_id"]
        added = collection_add_video(self._channel_name, video_id)
        title = event.video.get("title", video_id)
        if added:
            self._set_status(f"Added '{title}' to Collection.")
        else:
            self._set_status(f"'{title}' is already in Collection.")

    def on_video_list_sync_requested(self, event: VideoList.SyncRequested) -> None:
        self.post_message(self.SyncChannelRequested(self._channel_name, self._channel_url))

    # ------------------------------------------------------------------ CollectionList events
    def on_collection_list_video_selected(self, event: CollectionList.VideoSelected) -> None:
        library = load_library(self._channel_name)
        video_map = {v["video_id"]: v for v in library.get("videos", [])}
        video = video_map.get(event.video_id)
        if video:
            self._open_video(video)

    def on_collection_list_header_insert_requested(self, event: CollectionList.HeaderInsertRequested) -> None:
        self.app.push_screen(
            _TextInputScreen("Section header text:"),
            lambda text: self._do_insert_header(text, event.index),
        )

    def _do_insert_header(self, text: str | None, index: int) -> None:
        if text:
            collection_insert_header(self._channel_name, index, text)
            self._load_collection()

    def on_collection_list_note_edit_requested(self, event: CollectionList.NoteEditRequested) -> None:
        self.app.push_screen(
            _TextInputScreen("Note for this video:", initial=event.current_note),
            lambda text: self._do_set_note(event.video_id, text),
        )

    def _do_set_note(self, video_id: str, text: str | None) -> None:
        note = text if text is not None else ""
        collection_set_note(self._channel_name, video_id, note)
        self.query_one("#collection_list", CollectionList).refresh_item(video_id, note)

    # ------------------------------------------------------------------ Search
    def action_show_search(self) -> None:
        self.query_one("#search_bar", SearchBar).show()

    def on_search_bar_search_changed(self, event: SearchBar.SearchChanged) -> None:
        switcher = self.query_one("#content_switcher", ContentSwitcher)
        if switcher.current == "all_list":
            self.query_one("#all_list", VideoList).filter(event.query)

    def on_search_bar_search_closed(self, _: SearchBar.SearchClosed) -> None:
        self.query_one("#all_list", VideoList).filter("")

    # ------------------------------------------------------------------ Helpers
    def _open_video(self, video: dict[str, Any]) -> None:
        from tubevault.screens.video_detail import VideoDetailScreen
        self.app.push_screen(VideoDetailScreen(self._channel_name, video))

    def action_back(self) -> None:
        self.app.pop_screen()

    def _set_status(self, msg: str) -> None:
        self.query_one("#status_label", Label).update(msg)

    DEFAULT_CSS = """
    LibraryBrowserScreen {
        padding: 0;
    }
    #status_label {
        dock: bottom;
        height: 1;
        color: $success;
        padding: 0 1;
    }
    """


class _TextInputScreen(Screen):
    """Simple single-line text input modal."""

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, prompt: str, initial: str = "", **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._prompt = prompt
        self._initial = initial

    def compose(self) -> ComposeResult:
        yield Static(self._prompt, id="input_prompt")
        yield Input(value=self._initial, id="text_input")

    def on_mount(self) -> None:
        self.query_one("#text_input", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value.strip() or None)

    def action_cancel(self) -> None:
        self.dismiss(None)

    DEFAULT_CSS = """
    _TextInputScreen {
        align: center middle;
    }
    _TextInputScreen > * {
        width: 70;
        margin-bottom: 1;
    }
    #input_prompt {
        text-style: bold;
    }
    """
