"""Download/transcript/summary progress display panel."""

from typing import Any

from rich.table import Table
from rich.text import Text
from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import Label, Static

from tubevault.core.sync import ChannelSyncProgress


class ProgressPanel(Widget):
    """A panel showing sync progress for a channel.

    Displays overall progress and per-video progress slots arranged side by
    side (wrapping to additional rows when more videos are active than fit
    in one row).
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
    """

    def __init__(self, channel_name: str = "", **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._channel_name = channel_name
        self._prog: ChannelSyncProgress | None = None

    def compose(self) -> ComposeResult:
        yield Label("Sync Progress", classes="title")
        yield Label("", id="overall_label", classes="overall")
        yield Static("", id="video_slots")

    def update_progress(self, prog: ChannelSyncProgress) -> None:
        """Update the panel with new progress state.

        Args:
            prog: Current channel sync progress.
        """
        self._prog = prog
        self._refresh_display()

    def _refresh_display(self) -> None:
        if not self._prog or not self.is_mounted:
            return
        prog = self._prog

        overall = self.query_one("#overall_label", Label)
        overall.update(f"[{prog.completed}/{prog.total} videos synced]")

        slots = self.query_one("#video_slots", Static)

        if prog.done:
            if prog.error:
                slots.update(Text(f"Error: {prog.error}", style="red"))
            else:
                slots.update(Text("Sync complete.", style="green"))
            return

        active = prog.active_videos
        if not active:
            slots.update(Text("Preparing…", style="dim"))
            return

        slots.update(self._render_slots(active))

    def _render_slots(self, active: list) -> Any:
        """Build a Rich Table grid with one slot per active video.

        Each slot occupies 3 lines: title, progress bar, stage icons.
        Slots are arranged side by side and wrap to the next row when
        there are more active videos than fit in one row.
        """
        try:
            avail = max(40, self.size.width - 6)
        except Exception:
            avail = 76

        slot_min_width = 36
        cols = max(1, min(len(active), avail // slot_min_width))

        def _icon(status: Any) -> str:
            if isinstance(status, float):
                if status >= 1.0:
                    return "✓"
                if status < 0:
                    return "✗"
                return f"{int(status * 100)}%"
            return {
                "done": "✓",
                "in_progress": "⏳",
                "skipped": "—",
                "error": "✗",
                "pending": "·",
            }.get(status, status)

        def _bar(pct: int, width: int = 14) -> str:
            filled = int(pct / 100 * width)
            return "█" * filled + "░" * (width - filled) + f" {pct:3d}%"

        def _build_cell(vp: Any) -> Text:
            title = (vp.title[:30] + "…") if len(vp.title) > 31 else vp.title
            dl_pct = max(0, int(vp.download * 100))
            bar = _bar(dl_pct)
            dl_icon = _icon(vp.download)
            t_icon = _icon(vp.transcript)
            s_icon = _icon(vp.summary)
            cell = Text()
            cell.append(title + "\n", style="white")
            cell.append(bar + "\n", style="cyan")
            cell.append(f"DL:{dl_icon}  TR:{t_icon}  SUM:{s_icon}", style="dim")
            return cell

        table = Table.grid(expand=True, padding=(0, 1))
        for _ in range(cols):
            table.add_column(ratio=1)

        for row_start in range(0, len(active), cols):
            row_slots = active[row_start : row_start + cols]
            cells: list[Any] = [_build_cell(vp) for vp in row_slots]
            # Pad the last row with blank cells if it's short
            while len(cells) < cols:
                cells.append(Text(""))
            table.add_row(*cells)

        return table
