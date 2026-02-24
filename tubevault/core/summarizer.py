"""Anthropic Claude API integration for generating video summaries."""

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

from tubevault.core.transcript import transcript_to_text

logger = logging.getLogger(__name__)

MODEL = "claude-sonnet-4-20250514"

SYSTEM_PROMPT = """\
You are a content analyst. Given a video transcript with timestamps, produce a focused summary of the video's substantive content.

Rules:
- Completely ignore all sponsorship segments, affiliate offers, discount codes, merchandise plugs, calls to like/subscribe/comment, Patreon mentions, and any other promotional or marketing content. Do not mention these at all.
- Focus exclusively on the educational, informational, analytical, or entertainment substance of the video.
- Write a concise summary (3-8 paragraphs) in clear, direct prose.
- Extract 5-15 main points. For each point, include the timestamp range (start and end in seconds) where this information appears in the video.
- Be specific and factual. Include key claims, data points, names, and conclusions presented.

Respond in JSON format:
{
  "summary_text": "...",
  "main_points": [
    {"point": "...", "detail": "...", "start_time_seconds": N, "end_time_seconds": N}
  ]
}"""


def _get_client() -> Any:
    """Create and return an Anthropic client using the configured API key env var.

    Returns:
        anthropic.Anthropic client instance.

    Raises:
        RuntimeError: If the API key environment variable is not set.
    """
    import anthropic
    from tubevault.core.config import load_config

    config = load_config()
    env_var = config.get("anthropic_api_key_env", "ANTHROPIC_API_KEY")
    api_key = os.environ.get(env_var)
    if not api_key:
        raise RuntimeError(
            f"Anthropic API key not found. Set the {env_var!r} environment variable."
        )
    return anthropic.Anthropic(api_key=api_key)


async def generate_summary(
    video_id: str,
    segments: list[dict[str, Any]],
    title: str = "",
) -> dict[str, Any] | None:
    """Generate an AI summary for a video transcript.

    Args:
        video_id: YouTube video ID (used in the returned dict).
        segments: Transcript segments with ``text`` and ``start`` keys.
        title: Video title (included in prompt for context).

    Returns:
        Summary dict matching summary.json schema, or None on failure.
    """
    transcript_text = transcript_to_text(segments)
    if not transcript_text.strip():
        logger.warning("Empty transcript for %s — skipping summary", video_id)
        return None

    user_message = f"Video title: {title}\n\nTranscript:\n{transcript_text}"

    try:
        result = await asyncio.get_running_loop().run_in_executor(
            None, _call_api, user_message
        )
        return {
            "video_id": video_id,
            "generated_date": datetime.now(timezone.utc).isoformat(),
            "model_used": MODEL,
            **result,
        }
    except Exception as exc:
        logger.error("Summary generation failed for %s: %s", video_id, exc)
        return None


def _call_api(user_message: str) -> dict[str, Any]:
    """Make the synchronous Anthropic API call.

    Args:
        user_message: The user turn content.

    Returns:
        Parsed summary dict with ``summary_text`` and ``main_points``.

    Raises:
        RuntimeError: On API or parsing error.
    """
    client = _get_client()
    response = client.messages.create(
        model=MODEL,
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )
    raw = response.content[0].text.strip()

    # Strip markdown code fences if present
    if raw.startswith("```"):
        lines = raw.splitlines()
        raw = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Failed to parse API response as JSON: {exc}\nRaw: {raw[:500]}") from exc

    if "summary_text" not in parsed or "main_points" not in parsed:
        raise RuntimeError(f"Unexpected API response structure: {list(parsed.keys())}")

    return parsed


async def generate_master_summary(compiled_markdown: str) -> str | None:
    """Generate a master synthesis summary from compiled per-video summaries.

    Args:
        compiled_markdown: Full markdown text of all individual summaries.

    Returns:
        Master summary markdown text, or None on failure.
    """
    system = """\
You are a research synthesizer. Below are summaries of multiple videos from the same YouTube channel, ordered from newest to oldest.

Produce a master summary that:
1. Synthesizes the key themes and information across all videos
2. Organizes findings by topic/theme, not chronologically
3. Where information is contradictory between videos, note the contradiction and give higher weight to more recent videos (listed first)
4. Ignore any residual marketing or promotional content
5. Highlight any evolution of the creator's views or recommendations over time

Output clean, well-structured Markdown."""

    try:
        result = await asyncio.get_running_loop().run_in_executor(
            None, _call_master_api, system, compiled_markdown
        )
        return result
    except Exception as exc:
        logger.error("Master summary generation failed: %s", exc)
        return None


def _call_master_api(system: str, content: str) -> str:
    client = _get_client()
    response = client.messages.create(
        model=MODEL,
        max_tokens=8192,
        system=system,
        messages=[{"role": "user", "content": content}],
    )
    return response.content[0].text.strip()
