"""Synchronization progress screen — four independent slot quadrants."""

import asyncio
import contextvars
import logging
import warnings
from typing import Any

from rich.console import Group
from rich.table import Table
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.screen import Screen
from textual.widget import Widget
from textual.widgets import Footer, Header, Label, RichLog, Static

from tubevault.core.config import QUALITY_MAP, load_config
from tubevault.core.sync import (
    INTER_REQUEST_DELAY,
    ChannelSyncProgress,
    VideoProgress,
    sync_channel,
    sync_all_channels,
)
from tubevault.utils.helpers import load_proxy_url

logger = logging.getLogger(__name__)

# Total number of quadrant slots always shown in the UI.
SLOT_COUNT = 4
# Width (in block chars) of the ASCII download progress bar.
BAR_WIDTH = 16
# Braille spinner frames cycled during transcript / summary stages.
SPINNER_FRAMES = "⣾⣽⣻⢿⡿⣟⣯⣷"


def _fmt_bytes(n: int) -> str:
    if n >= 1024 ** 3:
        return f"{n / 1024 ** 3:.1f} GB"
    if n >= 1024 ** 2:
        return f"{n / 1024 ** 2:.0f} MB"
    if n >= 1024:
        return f"{n / 1024:.0f} KB"
    return f"{n} B"


def _render_slot_header(vp: VideoProgress, spinner_frame: int = 0) -> Group:
    """Build a 3-line Rich renderable for an active video slot.

    Line 1 — title (left) + channel name right-justified.
    Line 2 — current active stage: download bar, transcript spinner, or summary spinner.
    Line 3 — completed-stage checkmarks: Video / Transcript / Summary.
    """
    spinner = SPINNER_FRAMES[spinner_frame % len(SPINNER_FRAMES)]

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

    # --- Fetching-list state: single header line, no download/stage rows ---
    if vp.fetching:
        row = Table.grid(expand=True, padding=0)
        row.add_column(ratio=1, no_wrap=True, overflow="ellipsis")
        row.add_column(no_wrap=True)
        row.add_row(
            Text(f"{vp.title}  {spinner}", style="cyan"),
            Text(f" {vp.channel_name}", style="dim", justify="right"),
        )
        return Group(row)

    # --- Line 1: title left, channel name right ---
    title_row = Table.grid(expand=True, padding=0)
    title_row.add_column(ratio=1, no_wrap=True, overflow="ellipsis")
    title_row.add_column(no_wrap=True)
    title_row.add_row(
        Text(vp.title, style="white bold"),
        Text(f" {vp.channel_name}", style="dim", justify="right"),
    )

    # --- Line 2: active stage ---
    if vp.transcript == "in_progress":
        stage_line = Text(f"Fetching transcript  {spinner}", style="yellow")
    elif vp.summary == "in_progress":
        stage_line = Text(f"Generating summary  {spinner}", style="magenta")
    else:
        dl_pct = max(0, int(vp.download * 100))
        filled = int(dl_pct / 100 * BAR_WIDTH)
        bar = "▓" * filled + "░" * (BAR_WIDTH - filled)
        stage_style = "green" if vp.download >= 1.0 else "cyan"
        size_str = ""
        if vp.total_bytes > 0:
            size_str = f"  [{_fmt_bytes(vp.downloaded_bytes)} / {_fmt_bytes(vp.total_bytes)}]"
        elif vp.downloaded_bytes > 0:
            size_str = f"  [{_fmt_bytes(vp.downloaded_bytes)}]"
        quality_str = f"  {vp.quality}" if vp.quality else ""
        stage_line = Text(f"Downloading  {bar}  {dl_pct:3d}%{size_str}{quality_str}", style=stage_style)

    # --- Line 3: per-stage status icons ---
    dl_icon = _icon(vp.download)
    t_icon = _icon(vp.transcript)
    s_icon = _icon(vp.summary)

    dl_style = "green" if vp.download >= 1.0 else ("red" if isinstance(vp.download, float) and vp.download < 0 else "cyan")
    t_style = "green" if vp.transcript == "done" else ("dim" if vp.transcript == "pending" else "yellow")
    s_style = "green" if vp.summary == "done" else ("dim" if vp.summary == "pending" else "yellow")

    status_line = Text()
    status_line.append("Video  ", style="dim")
    status_line.append(dl_icon, style=dl_style)
    status_line.append("   Transcript  ", style="dim")
    status_line.append(t_icon, style=t_style)
    status_line.append("   Summary  ", style="dim")
    status_line.append(s_icon, style=s_style)

    return Group(title_row, stage_line, status_line)


class SyncSlot(Widget):
    """One quadrant of the sync screen: a status header and a per-thread log."""

    def __init__(self, slot_idx: int, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._slot_idx = slot_idx
        self._vp: VideoProgress | None = None
        self._spinner_frame: int = 0

    def compose(self) -> ComposeResult:
        yield Static(
            Text(f"  Slot {self._slot_idx + 1}  —  idle", style="dim"),
            id=f"slot_header_{self._slot_idx}",
            classes="slot-header",
        )
        yield RichLog(
            highlight=False,
            markup=False,
            wrap=True,
            id=f"slot_log_{self._slot_idx}",
            classes="slot-log",
        )

    def on_mount(self) -> None:
        # Animate spinner for transcript / summary stages at ~8 fps.
        self.set_interval(0.125, self._tick_spinner)

    def _tick_spinner(self) -> None:
        """Advance spinner frame and redraw header if in an animated stage."""
        if self._vp is not None and (
            self._vp.fetching
            or self._vp.transcript == "in_progress"
            or self._vp.summary == "in_progress"
        ):
            self._spinner_frame += 1
            self._update_header()

    def set_idle(self) -> None:
        self._vp = None
        try:
            h = self.query_one(f"#slot_header_{self._slot_idx}", Static)
            if h.is_mounted:
                h.update(Text(f"  Slot {self._slot_idx + 1}  —  idle", style="dim"))
        except Exception:
            pass

    def update_video(self, vp: VideoProgress) -> None:
        self._vp = vp
        self._update_header()

    def _update_header(self) -> None:
        if self._vp is None:
            return
        try:
            h = self.query_one(f"#slot_header_{self._slot_idx}", Static)
            if h.is_mounted:
                h.update(_render_slot_header(self._vp, self._spinner_frame))
        except Exception:
            pass

    def write_log(self, msg: Any) -> None:
        try:
            log = self.query_one(f"#slot_log_{self._slot_idx}", RichLog)
            if log.is_mounted:
                if isinstance(msg, Text):
                    log.write(msg)
                else:
                    # Use from_ansi so yt-dlp's ANSI color codes are converted
                    # to Rich styling rather than rendered as raw ESC characters.
                    log.write(Text.from_ansi(str(msg)))
        except Exception:
            pass


class SyncScreen(Screen):
    """Full-screen sync progress display.

    The sync runs as an App-level worker so it survives this screen being
    popped.  Returning to this screen replays accumulated per-slot log lines
    and shows the latest progress state.
    """

    TITLE = "TubeVault"
    BINDINGS = [Binding("escape", "back", "Back (sync continues)", priority=True)]

    def __init__(
        self,
        channel_name: str | None = None,
        channel_url: str | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._channel_name = channel_name
        self._channel_url = channel_url

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Label("Press Escape to return; sync continues in background.", id="sync_hint")
        yield Label("", id="sync_config_label")
        yield Label("", id="overall_label")
        yield Label("", id="countdown_label")
        with Horizontal(id="row_top"):
            yield SyncSlot(0, id="slot_0")
            yield SyncSlot(1, id="slot_1")
        with Horizontal(id="row_bottom"):
            yield SyncSlot(2, id="slot_2")
            yield SyncSlot(3, id="slot_3")
        yield Footer()

    def on_mount(self) -> None:
        self._populate_config_label()

        # Replay per-slot logs accumulated while this screen was not visible.
        slot_logs = getattr(self.app, "sync_slot_logs", [[], [], [], []])
        for i in range(SLOT_COUNT):
            logs = slot_logs[i] if i < len(slot_logs) else []
            try:
                slot = self.query_one(f"#slot_{i}", SyncSlot)
                for msg in logs:
                    slot.write_log(msg)
            except Exception:
                pass

        # Show the latest progress snapshot.
        if self.app.sync_progress is not None:
            self._deliver_progress(self.app.sync_progress)

        # Only start a new sync if one is not already running.
        if not self.app.sync_running:
            self.app.sync_slot_logs = [[], [], [], []]
            self.app.sync_progress = None
            self.app.run_worker(self._run_sync(), exclusive=False)

    async def _run_sync(self) -> None:
        loop = asyncio.get_running_loop()
        # Capture context (includes Textual's active_app ContextVar) so
        # call_soon_threadsafe callbacks can access widgets safely.
        ctx = contextvars.copy_context()

        self.app.sync_running = True

        def _write_log(msg: Any) -> None:
            # Channel-level messages (fetching list, completion) go to slot 0.
            logs = getattr(self.app, "sync_slot_logs", None)
            if logs:
                logs[0].append(msg)
            loop.call_soon_threadsafe(ctx.run, self._deliver_slot_log, msg, 0)

        def _slot_log_callback(slot_idx: int, msg: Any) -> None:
            logs = getattr(self.app, "sync_slot_logs", None)
            if logs and slot_idx < len(logs):
                logs[slot_idx].append(msg)
            loop.call_soon_threadsafe(ctx.run, self._deliver_slot_log, msg, slot_idx)

        def _progress_callback(prog: ChannelSyncProgress) -> None:
            self.app.sync_progress = prog
            loop.call_soon_threadsafe(ctx.run, self._deliver_progress, prog)

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            try:
                if self._channel_name and self._channel_url:
                    config = load_config()
                    ch = next(
                        (c for c in config.get("channels", []) if c["name"] == self._channel_name),
                        {},
                    )
                    quality = QUALITY_MAP.get(ch.get("quality", "high"), "1080p")
                    max_concurrent = config.get("max_concurrent_downloads", 2)
                    await sync_channel(
                        channel_name=self._channel_name,
                        channel_url=self._channel_url,
                        quality=quality,
                        max_concurrent=max_concurrent,
                        progress_callback=_progress_callback,
                        log_callback=_write_log,
                        slot_log_callback=_slot_log_callback,
                    )
                else:
                    await sync_all_channels(
                        progress_callback=_progress_callback,
                        log_callback=_write_log,
                        slot_log_callback=_slot_log_callback,
                    )
            except Exception as exc:
                logger.error("Sync error: %s", exc)
                err_msg = f"ERROR: {exc}"
                logs = getattr(self.app, "sync_slot_logs", None)
                if logs:
                    logs[0].append(err_msg)
                loop.call_soon_threadsafe(ctx.run, self._deliver_slot_log, err_msg, 0)
            finally:
                self.app.sync_running = False

    def _deliver_slot_log(self, msg: Any, slot_idx: int) -> None:
        """Write a log line to the correct slot widget on the current SyncScreen."""
        for screen in self.app.screen_stack:
            if isinstance(screen, SyncScreen):
                try:
                    slot = screen.query_one(f"#slot_{slot_idx}", SyncSlot)
                    slot.write_log(msg)
                except Exception:
                    pass
                return

    def _deliver_progress(self, prog: ChannelSyncProgress) -> None:
        """Update all slot headers and the overall label on the current SyncScreen."""
        for screen in self.app.screen_stack:
            if isinstance(screen, SyncScreen):
                try:
                    # Overall progress label
                    overall = screen.query_one("#overall_label", Label)
                    if overall.is_mounted:
                        if prog.done:
                            if prog.error:
                                overall.update(Text(f"Error: {prog.error}", style="red"))
                            else:
                                overall.update(
                                    Text(f"Sync complete — {prog.completed} videos processed.", style="green")
                                )
                        else:
                            overall.update(f"[{prog.completed}/{prog.total} videos synced]")

                    # Per-slot headers
                    for i in range(SLOT_COUNT):
                        try:
                            slot = screen.query_one(f"#slot_{i}", SyncSlot)
                            vp = prog.slots[i] if i < len(prog.slots) else None
                            if vp is not None:
                                slot.update_video(vp)
                            else:
                                slot.set_idle()
                        except Exception:
                            pass

                    # Countdown label (inter-request delay, no-proxy only)
                    lbl = screen.query_one("#countdown_label", Label)
                    if lbl.is_mounted:
                        if prog.retry_countdown > 0:
                            style = "bold orange1" if prog.retry_message.startswith("⏳") else "dim cyan"
                            lbl.update(Text(prog.retry_message, style=style))
                        else:
                            lbl.update("")
                except Exception:
                    pass
                return

    def _populate_config_label(self) -> None:
        proxy_url = load_proxy_url()

        if proxy_url:
            from urllib.parse import urlparse
            p = urlparse(proxy_url)
            proxy_display = f"{p.hostname}:{p.port}"
            threads_display = str(SLOT_COUNT)
            spacing_display = "none"
        else:
            proxy_display = "none"
            threads_display = "1"
            spacing_display = f"{INTER_REQUEST_DELAY}s"

        t = Text()
        t.append("Proxy: ", style="dim")
        t.append(proxy_display, style="cyan")
        t.append("   Threads: ", style="dim")
        t.append(threads_display, style="cyan")
        t.append("   Request spacing: ", style="dim")
        t.append(spacing_display, style="cyan")
        self.query_one("#sync_config_label", Label).update(t)

    def action_back(self) -> None:
        self.app.pop_screen()

    DEFAULT_CSS = """
    SyncScreen {
        padding: 0 2;
        layout: vertical;
    }
    #sync_hint {
        color: $text-muted;
        height: 1;
    }
    #sync_config_label {
        width: 100%;
        height: 1;
    }
    #overall_label {
        width: 100%;
        height: 1;
        color: $text-muted;
    }
    #countdown_label {
        width: 100%;
        height: 1;
        margin-bottom: 0;
    }
    #row_top, #row_bottom {
        height: 1fr;
        layout: horizontal;
    }
    SyncSlot {
        width: 1fr;
        height: 100%;
        border: solid $panel-lighten-2;
    }
    .slot-header {
        height: auto;
        padding: 1 1;
        border-bottom: solid $panel-lighten-2;
        background: $panel-darken-1;
    }
    .slot-log {
        height: 1fr;
        padding: 0 1;
        background: $panel;
        scrollbar-size-vertical: 0;
    }
    """
