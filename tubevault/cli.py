"""Click CLI entry point for TubeVault."""

import asyncio
import logging
import sys
from pathlib import Path
from typing import Any

import click

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stderr,
)

logger = logging.getLogger(__name__)


@click.command()
@click.option("--sync", is_flag=True, default=False, help="Run headless sync and exit.")
@click.option("--channel", default=None, help="Channel name/slug to operate on.")
@click.option("--export", "do_export", is_flag=True, default=False, help="Export summaries to Markdown.")
@click.option("--output", default=None, type=click.Path(), help="Output file for --export.")
@click.option("--master-summary", is_flag=True, default=False, help="Include AI master summary in export.")
@click.option("--verbose", "-v", is_flag=True, default=False, help="Enable verbose logging.")
def main(
    sync: bool,
    channel: str | None,
    do_export: bool,
    output: str | None,
    master_summary: bool,
    verbose: bool,
) -> None:
    """TubeVault — YouTube video library manager with AI summaries.

    Run without flags to launch the TUI.
    """
    if verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    if sync:
        _run_sync(channel)
    elif do_export:
        _run_export(channel, output, master_summary)
    else:
        _run_tui()


def _run_sync(channel: str | None) -> None:
    """Headless sync mode."""
    from tubevault.core.config import load_config
    from tubevault.core.sync import sync_all_channels, sync_channel

    config = load_config()
    quality = config.get("download_quality", "1080p")
    max_concurrent = config.get("max_concurrent_downloads", 2)

    def _log_progress(prog: Any) -> None:
        if prog.current_video:
            vp = prog.current_video
            if vp.download >= 1.0:
                dl = "done"
            elif vp.download < 0:
                dl = "err"
            else:
                dl = f"{int(vp.download * 100)}%"
            logger.info(
                "[%d/%d] %s — dl:%s t:%s s:%s",
                prog.completed,
                prog.total,
                vp.title[:60],
                dl,
                vp.transcript,
                vp.summary,
            )

    if channel:
        channels = config.get("channels", [])
        ch = next((c for c in channels if c["name"] == channel), None)
        if not ch:
            click.echo(f"Channel '{channel}' not found in config.", err=True)
            sys.exit(1)
        asyncio.run(
            sync_channel(
                channel_name=ch["name"],
                channel_url=ch["url"],
                quality=quality,
                max_concurrent=max_concurrent,
                progress_callback=_log_progress,
            )
        )
    else:
        asyncio.run(sync_all_channels(progress_callback=_log_progress))

    click.echo("Sync complete.")


def _run_export(channel: str | None, output: str | None, master_summary: bool) -> None:
    """Headless export mode."""
    from tubevault.core.exporter import export_channel

    if not channel:
        click.echo("--channel is required for --export.", err=True)
        sys.exit(1)

    out_path = Path(output) if output else Path(f"{channel}_summaries.md")
    asyncio.run(export_channel(channel, out_path, include_master_summary=master_summary))
    click.echo(f"Exported to {out_path}")


def _run_tui() -> None:
    """Launch the Textual TUI."""
    from tubevault.app import TubeVaultApp

    app = TubeVaultApp()
    app.run()
