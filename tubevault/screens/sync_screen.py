"""Synchronization progress screen — four independent slot quadrants."""

import asyncio
import contextvars
import logging
import warnings
from typing import Any

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.screen import Screen
from textual.widget import Widget
from textual.widgets import Footer, Header, Label, RichLog, Static

from tubevault.core.config import load_config
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
BAR_WIDTH = 22


def _render_slot_header(vp: VideoProgress) -> Text:
    """Build a 3-line Rich Text header for an active video slot."""
    title = (vp.title[:36] + "…") if len(vp.title) > 37 else vp.title

    dl_pct = max(0, int(vp.download * 100))
    filled = int(dl_pct / 100 * BAR_WIDTH)
    bar = "▓" * filled + "░" * (BAR_WIDTH - filled)

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
            "pending": "pending",
        }.get(status, status)

    t_icon = _icon(vp.transcript)
    s_icon = _icon(vp.summary)

    t_style = "green" if vp.transcript == "done" else ("dim" if vp.transcript == "pending" else "yellow")
    s_style = "green" if vp.summary == "done" else ("dim" if vp.summary == "pending" else "yellow")

    t = Text()
    t.append(title + "\n", style="white bold")
    t.append("Downloading  ", style="dim")
    t.append(bar, style="cyan")
    t.append(f"  {dl_pct:3d}%\n", style="cyan bold")
    t.append("Transcript  ", style="dim")
    t.append(t_icon, style=t_style)
    t.append("    Summary  ", style="dim")
    t.append(s_icon, style=s_style)
    return t


class SyncSlot(Widget):
    """One quadrant of the sync screen: a status header and a per-thread log."""

    def __init__(self, slot_idx: int, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._slot_idx = slot_idx

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

    def set_idle(self) -> None:
        try:
            h = self.query_one(f"#slot_header_{self._slot_idx}", Static)
            if h.is_mounted:
                h.update(Text(f"  Slot {self._slot_idx + 1}  —  idle", style="dim"))
        except Exception:
            pass

    def update_video(self, vp: VideoProgress) -> None:
        try:
            h = self.query_one(f"#slot_header_{self._slot_idx}", Static)
            if h.is_mounted:
                h.update(_render_slot_header(vp))
        except Exception:
            pass

    def write_log(self, msg: Any) -> None:
        try:
            log = self.query_one(f"#slot_log_{self._slot_idx}", RichLog)
            if log.is_mounted:
                log.write(msg if isinstance(msg, Text) else Text(str(msg)))
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
                    quality = config.get("download_quality", "1080p")
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
        height: 5;
        padding: 1 1;
        border-bottom: solid $panel-lighten-2;
        background: $panel-darken-1;
    }
    .slot-log {
        height: 1fr;
        padding: 0 1;
        background: $panel;
    }
    """
