"""Click CLI entry point for TubeVault."""

import asyncio
import logging
import sys
from pathlib import Path
from typing import Any

import click

# Do NOT configure logging here at module level — it would write to stderr
# and corrupt the Textual terminal when running in TUI mode.
# Headless modes (--sync, --export) configure logging themselves.
logging.getLogger().addHandler(logging.NullHandler())

logger = logging.getLogger(__name__)


@click.command()
@click.option("--sync", is_flag=True, default=False, help="Run headless sync and exit.")
@click.option("--fix-dates", is_flag=True, default=False, help="Fetch channel listings and populate missing publish dates, then exit.")
@click.option("--channel", default=None, help="Channel name/slug to operate on.")
@click.option("--export", "do_export", is_flag=True, default=False, help="Export summaries to Markdown.")
@click.option("--output", default=None, type=click.Path(), help="Output file for --export.")
@click.option("--master-summary", is_flag=True, default=False, help="Include AI master summary in export.")
@click.option("--verbose", "-v", is_flag=True, default=False, help="Enable verbose logging.")
def main(
    sync: bool,
    fix_dates: bool,
    channel: str | None,
    do_export: bool,
    output: str | None,
    master_summary: bool,
    verbose: bool,
) -> None:
    """TubeVault — YouTube video library manager with AI summaries.

    Run without flags to launch the TUI.
    """
    if sync or fix_dates or do_export:
        _configure_headless_logging(verbose)

    if sync:
        _run_sync(channel)
    elif fix_dates:
        _run_fix_dates(channel)
    elif do_export:
        _run_export(channel, output, master_summary)
    else:
        _run_tui()


def _configure_headless_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stderr,
    )


def _run_sync(channel: str | None) -> None:
    """Headless sync mode."""
    from tubevault.core.config import load_config
    from tubevault.core.sync import sync_all_channels, sync_channel

    config = load_config()
    quality = config.get("download_quality", "1080p")
    max_concurrent = config.get("max_concurrent_downloads", 2)

    def _log_progress(prog: Any) -> None:
        for vp in (v for v in (prog.slots or []) if v is not None):
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


def _run_fix_dates(channel: str | None) -> None:
    """Fetch channel listings and backfill missing publish dates."""
    from tubevault.core.config import load_config
    from tubevault.core.database import batch_update_upload_dates, list_library_page_nums, load_library_page
    from tubevault.core.downloader import fetch_channel_videos

    config = load_config()
    channels_cfg = config.get("channels", [])

    if channel:
        channels_cfg = [c for c in channels_cfg if c["name"] == channel]
        if not channels_cfg:
            click.echo(f"Channel '{channel}' not found in config.", err=True)
            sys.exit(1)

    total_updated = 0
    for ch in channels_cfg:
        ch_name = ch["name"]
        ch_url = ch["url"]

        # Count how many videos are missing a date before we start.
        missing = sum(
            1
            for pn in list_library_page_nums(ch_name)
            for v in load_library_page(ch_name, pn)["videos"]
            if not v.get("upload_date")
        )
        if not missing:
            click.echo(f"{ch_name}: all dates present, skipping.")
            continue

        click.echo(f"{ch_name}: fetching video listing ({missing} dates missing)…")
        try:
            videos = asyncio.run(fetch_channel_videos(ch_url, stop_at_ids=None))
        except Exception as exc:
            click.echo(f"{ch_name}: fetch failed — {exc}", err=True)
            continue

        date_map = {v["video_id"]: v["upload_date"] for v in videos if v.get("upload_date")}
        updated = batch_update_upload_dates(ch_name, date_map)
        total_updated += updated
        click.echo(f"{ch_name}: updated {updated} / {missing} entries.")

    click.echo(f"Done. {total_updated} dates populated across all channels.")


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
    # Textual's teardown doesn't always restore the cursor; force it here
    # after run() returns and the terminal is fully back to normal mode.
    sys.stdout.write("\x1b[?25h")
    sys.stdout.flush()
