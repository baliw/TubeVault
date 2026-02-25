"""Shared utility functions for TubeVault."""

import asyncio
import logging
import threading
from datetime import timedelta
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)


async def run_in_daemon_thread(func: Callable[..., Any], *args: Any) -> Any:
    """Run a blocking function on a daemon thread and await the result.

    Unlike loop.run_in_executor(None, ...), the thread created here is a
    daemon thread and will not block the process from exiting when the app
    closes while a yt-dlp download or transcript fetch is in flight.
    """
    loop = asyncio.get_running_loop()
    fut: asyncio.Future = loop.create_future()

    def _run() -> None:
        try:
            result = func(*args)
            if not fut.done():
                loop.call_soon_threadsafe(fut.set_result, result)
        except BaseException as exc:
            if not fut.done():
                loop.call_soon_threadsafe(fut.set_exception, exc)

    threading.Thread(target=_run, daemon=True, name="tubevault-worker").start()
    return await fut


def format_duration(seconds: int) -> str:
    """Format duration in seconds to HH:MM:SS or MM:SS string.

    Args:
        seconds: Duration in seconds.

    Returns:
        Formatted duration string.
    """
    td = timedelta(seconds=seconds)
    total_seconds = int(td.total_seconds())
    hours, remainder = divmod(total_seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def format_timestamp(seconds: int) -> str:
    """Format seconds to MM:SS timestamp string.

    Args:
        seconds: Time in seconds.

    Returns:
        MM:SS formatted string.
    """
    minutes, secs = divmod(int(seconds), 60)
    return f"{minutes:02d}:{secs:02d}"


def ensure_dir(path: Path) -> Path:
    """Ensure a directory exists, creating it if necessary.

    Args:
        path: Directory path to ensure.

    Returns:
        The path, guaranteed to exist.
    """
    path.mkdir(parents=True, exist_ok=True)
    return path


def load_proxy_url() -> str | None:
    """Load proxy configuration from proxy.conf next to the package root.

    Returns:
        Proxy URL string in the form ``http://user:pass@host:port``,
        or None if proxy.conf is absent or incomplete.
    """
    conf = Path(__file__).parent.parent.parent / "proxy.conf"
    if not conf.exists():
        return None
    data: dict[str, str] = {}
    for line in conf.read_text().splitlines():
        line = line.strip()
        if "=" in line:
            key, _, val = line.partition("=")
            data[key.strip()] = val.strip()
    host = data.get("proxy_domain")
    port = data.get("proxy_port")
    user = data.get("proxy_user")
    password = data.get("proxy_password")
    if not (host and port):
        return None
    if user and password:
        return f"http://{user}:{password}@{host}:{port}"
    return f"http://{host}:{port}"


def tubevault_root() -> Path:
    """Return the root TubeVault data directory.

    Returns:
        Path to ~/TubeVault/.
    """
    root = Path.home() / "TubeVault"
    ensure_dir(root)
    return root
