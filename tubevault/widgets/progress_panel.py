"""Download/transcript/summary progress display panel."""

from typing import Any

from rich.text import Text
from textual.app import ComposeResult
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Label, ProgressBar, Static

from tubevault.core.sync import ChannelSyncProgress


class ProgressPanel(Widget):
    """A panel showing sync progress for a channel.

    Displays overall progress and per-video progress bars.
    """

    DEFAULT_CSS = """
    ProgressPanel {
        border: solid $accent;
        padding: 1 2;
        height: auto;
    }
    ProgressPanel .title {
        text-style: bold;
        color: $text;
        margin-bottom: 1;
    }
    ProgressPanel .overall {
        color: $text-muted;
        margin-bottom: 1;
    }
    ProgressPanel .video-title {
        color: $text;
        margin-bottom: 0;
    }
    ProgressPanel .status-row {
        color: $text-muted;
    }
    """

    def __init__(self, channel_name: str = "", **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._channel_name = channel_name
        self._prog: ChannelSyncProgress | None = None

    def compose(self) -> ComposeResult:
        yield Label("Sync Progress", classes="title")
        yield Label("", id="overall_label", classes="overall")
        yield Label("", id="video_title_label", classes="video-title")
        yield ProgressBar(total=100, id="download_bar", show_eta=False)
        yield Label("", id="status_label", classes="status-row")

    def update_progress(self, prog: ChannelSyncProgress) -> None:
        """Update the panel with new progress state.

        Args:
            prog: Current channel sync progress.
        """
        self._prog = prog
        self._refresh_display()

    def _refresh_display(self) -> None:
        if not self._prog:
            return
        prog = self._prog

        overall = self.query_one("#overall_label", Label)
        overall.update(f"[{prog.completed}/{prog.total} videos synced]")

        video_label = self.query_one("#video_title_label", Label)
        download_bar = self.query_one("#download_bar", ProgressBar)
        status_label = self.query_one("#status_label", Label)

        if prog.done:
            if prog.error:
                video_label.update(f"Error: {prog.error}")
            else:
                video_label.update("Sync complete.")
            download_bar.update(progress=100)
            status_label.update("")
            return

        vp = prog.current_video
        if not vp:
            video_label.update("Preparing…")
            return

        video_label.update(vp.title)

        # Download progress bar
        dl_pct = int(vp.download * 100) if vp.download >= 0 else 0
        download_bar.update(progress=dl_pct)

        # Status icons
        def _icon(status: str | float) -> str:
            if isinstance(status, float):
                if status >= 1.0:
                    return "✓"
                if status < 0:
                    return "✗"
                return f"{int(status * 100)}%"
            return {"done": "✓", "in_progress": "⏳", "skipped": "—", "error": "✗", "pending": "·"}.get(status, status)

        dl_icon = _icon(vp.download)
        t_icon = _icon(vp.transcript)
        s_icon = _icon(vp.summary)

        text = Text()
        text.append(f"Download {dl_icon}  ", style="cyan")
        text.append(f"Transcript {t_icon}  ", style="green" if vp.transcript == "done" else "yellow")
        text.append(f"Summary {s_icon}", style="green" if vp.summary == "done" else "yellow")
        status_label.update(text)
