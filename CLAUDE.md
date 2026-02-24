# CLAUDE.md — TubeVault

## Project Overview

**TubeVault** is a command-line Python application that downloads YouTube videos and transcripts, organizes them by channel, and provides AI-generated summaries. It features a full TUI (Terminal User Interface) built with Rich + Textual for browsing and managing a local video library, as well as a headless mode for cron-based synchronization.

---

## Tech Stack

- **Language:** Python 3.11+
- **TUI Framework:** Textual (with Rich for rendering)
- **YouTube Downloads:** yt-dlp
- **Transcripts:** youtube-transcript-api (fallback: yt-dlp subtitle extraction)
- **AI Summaries:** Anthropic Claude API (claude-sonnet-4-20250514 via `anthropic` Python SDK)
- **Database:** JSON flat file (`library.json`) stored per-channel in the videos directory
- **HTML Playback:** Jinja2 templates for generating temporary local video player pages
- **Browser Launch:** `webbrowser` stdlib module
- **CLI Framework:** `click` for command-line argument parsing
- **Markdown Export:** Built-in, no extra dependency beyond `markdownify` if needed

---

## Directory Structure

```
~/TubeVault/
├── config.json                     # Global config: list of channels, API keys, preferences
├── videos/
│   └── [channel_name]/
│       ├── library.json            # Flat-file DB for this channel (all video metadata)
│       ├── collection.json         # User-curated collection: ordering, sections, notes
│       ├── [video_id]/
│       │   ├── video.mp4           # Downloaded video file
│       │   ├── transcript.json     # Raw transcript with timestamps
│       │   ├── summary.json        # AI-generated summary with timestamped points
│       │   └── metadata.json       # Video metadata (title, date, duration, thumbnail URL)
```

### Source Code Layout

```
tubevault/
├── __init__.py
├── __main__.py                     # Entry point: `python -m tubevault`
├── cli.py                          # Click CLI: --headless, --sync, --export flags
├── app.py                          # Textual App class (root TUI application)
├── screens/
│   ├── __init__.py
│   ├── channel_select.py           # Startup screen: pick channel, add/remove channels
│   ├── library_browser.py          # Main screen with "All" and "Collection" tabs
│   ├── video_detail.py             # Video detail view / launch player action
│   └── sync_screen.py             # Synchronization progress display
├── widgets/
│   ├── __init__.py
│   ├── video_list.py               # Scrollable video list widget (used in All tab)
│   ├── collection_list.py          # Editable ordered list with sections/notes (Collection tab)
│   ├── tab_bar.py                  # Top tab bar: "All" | "Collection"
│   ├── progress_panel.py           # Download/transcript/summary progress bars
│   └── search_bar.py              # Optional: filter/search videos
├── core/
│   ├── __init__.py
│   ├── downloader.py               # yt-dlp wrapper: download video, metadata, thumbnails
│   ├── transcript.py               # Transcript fetching and parsing (with timestamps)
│   ├── summarizer.py               # Anthropic API: generate summaries from transcripts
│   ├── sync.py                     # Orchestrator: sync all channels (download + transcript + AI)
│   ├── database.py                 # Read/write library.json and collection.json
│   ├── config.py                   # Global config management (config.json)
│   ├── exporter.py                 # Export summaries to markdown + master summary
│   └── html_player.py             # Generate temp HTML page, launch browser
├── templates/
│   └── player.html                 # Jinja2 template for local video playback page
└── utils/
    ├── __init__.py
    └── helpers.py                  # Shared utilities
```

---

## Core Features & Behavior

### 1. Channel Selection Screen (Startup)

When the TUI launches, present a selection screen listing all configured channels from `config.json`. Options:

- **Select a channel** → navigate into the library browser for that channel
- **Add channel** → prompt for YouTube channel URL or handle; validate and add to config
- **Remove channel** → select a channel to remove (confirm with user; optionally delete downloaded files)
- **Synchronize All** → trigger sync for all channels (enters sync screen)

Navigation: Arrow keys to highlight, Enter to select, Escape to quit.

### 2. Library Browser (Main Screen)

Two tabs at the top of the screen, selectable with arrow keys or Tab key:

#### "All" Tab
- Displays every video in `library.json` for the selected channel, sorted by upload date (newest first by default)
- Each row shows: title, upload date, duration, sync status icons (✓ video, ✓ transcript, ✓ summary)
- Arrow keys to scroll, Enter to select a video (opens detail/player), Escape to go back to channel select
- Pressing `a` on a highlighted video adds it to the Collection
- Pressing `s` triggers Synchronize for the current channel

#### "Collection" Tab
- Displays the user's curated list from `collection.json`
- Starts **blank** — user adds videos here from the "All" tab
- Supports:
  - **Reordering:** `Ctrl+Up` / `Ctrl+Down` (or `K`/`J`) to move a video up/down
  - **Section Headers:** Press `h` to insert a section header above the current item (prompted for text)
  - **Notes:** Press `n` on a video to add/edit a note annotation that displays below the video title
  - **Remove:** Press `d` or `Delete` to remove from collection (does not delete the video)
- Enter to select a video (opens detail/player), Escape to go back

### 3. Synchronization

Triggered via the TUI ("Synchronize" option) or headless CLI (`--sync`).

**Sync workflow per channel:**
1. Fetch the channel's full video list from YouTube (via yt-dlp channel extraction)
2. Compare against `library.json` — identify new videos not yet downloaded
3. For each new video:
   a. Download video (mp4, best quality up to 1080p) → show progress bar
   b. Download/extract transcript with timestamps → show progress indicator
   c. Send transcript to Claude API for summary generation → show progress indicator
   d. Save all artifacts to `[video_id]/` subdirectory
   e. Update `library.json` with new entry
4. For existing videos missing transcript or summary, backfill them

**AI Summary instructions (system prompt for summarizer):**
- Produce a concise summary (3-8 paragraphs) of the video's substantive content
- Extract 5-15 main points, each with the timestamp range where it appears in the video
- **Ignore all marketing, sponsorship segments, affiliate offers, discount codes, calls to subscribe, and promotional content entirely** — do not mention them
- Focus on educational, informational, or entertainment value only
- Output format: JSON with `summary_text`, `main_points[]` (each with `point`, `start_time_seconds`, `end_time_seconds`, `detail`)

**Progress display in TUI:** A panel showing:
- Overall channel progress: `[3/47 videos synced]`
- Current video: title + individual progress bars for download, transcript, summary
- Each progress bar labeled: `Downloading ████░░░░ 45%`, `Transcript ✓`, `Summary ⏳`

### 4. Video Playback (HTML Player)

When a video is selected (Enter key):
1. Generate a temporary HTML file using the Jinja2 template in `templates/player.html`
2. The HTML page contains:
   - An HTML5 `<video>` player with the local `.mp4` file as source (use `file://` URI)
   - Below the player: the AI summary text, rendered as readable HTML
   - Each main point in the summary is a clickable hyperlink that calls JavaScript to seek the video player to `start_time_seconds` for that point
   - Basic styling: dark theme, readable typography, responsive layout
3. Open the HTML file with `webbrowser.open()` using the system's default browser
4. Clean up temp files on next launch or app exit

**HTML player template requirements:**
- Video player with standard controls (play, pause, seek, volume, fullscreen)
- Summary section with heading "Summary"
- Main points rendered as a clickable/jumpable list with timestamps shown as `[MM:SS]`
- JavaScript: `document.getElementById('player').currentTime = seconds;` on link click
- Inline CSS, no external dependencies — must work fully offline

### 5. Headless Mode (CLI)

```bash
# Sync all channels (for cron)
python -m tubevault --sync

# Sync a specific channel
python -m tubevault --sync --channel "channel_name"

# Export summaries for a channel
python -m tubevault --export --channel "channel_name" --output summaries.md

# Export with master summary
python -m tubevault --export --channel "channel_name" --output summaries.md --master-summary

# Launch TUI (default)
python -m tubevault
```

Headless mode produces no TUI — only log output to stdout/stderr. Suitable for cron jobs.

### 6. Markdown Export

When exporting summaries (`--export` or via TUI menu):

1. Gather all summaries for the channel, sorted by video upload date (newest first)
2. Generate a single Markdown file:
   ```markdown
   # TubeVault Summary Export: [Channel Name]
   Generated: [date]

   ---

   ## [Video Title]
   **Date:** [upload date] | **Duration:** [HH:MM:SS]

   [Summary text]

   ### Key Points
   - **[MM:SS]** — [Point description]
   - **[MM:SS]** — [Point description]
   ...

   ---
   (repeat for each video)
   ```
3. If `--master-summary` is specified, after compiling all individual summaries:
   - Send the full compiled markdown to Claude API
   - System prompt: "Produce a master summary that synthesizes all the individual video summaries below. Where information is contradictory, weigh more recent videos higher and note the contradiction. Ignore all marketing and affiliate content. Organize by theme/topic."
   - Prepend the master summary to the export file under a `# Master Summary` heading

---

## Data Schemas

### config.json
```json
{
  "channels": [
    {
      "name": "channel_name",
      "url": "https://www.youtube.com/@channelhandle",
      "added_date": "2025-01-15T10:30:00Z",
      "auto_sync": true
    }
  ],
  "anthropic_api_key_env": "ANTHROPIC_API_KEY",
  "download_quality": "1080p",
  "max_concurrent_downloads": 2
}
```

### library.json (per channel)
```json
{
  "channel_name": "channel_name",
  "last_synced": "2025-06-01T12:00:00Z",
  "videos": [
    {
      "video_id": "dQw4w9WgXcQ",
      "title": "Video Title",
      "upload_date": "2025-05-20",
      "duration_seconds": 1234,
      "description": "...",
      "thumbnail_url": "https://...",
      "has_video": true,
      "has_transcript": true,
      "has_summary": true,
      "file_size_mb": 245.3,
      "added_date": "2025-06-01T12:00:00Z"
    }
  ]
}
```

### collection.json (per channel)
```json
{
  "channel_name": "channel_name",
  "items": [
    {
      "type": "section_header",
      "text": "Getting Started",
      "id": "sec_001"
    },
    {
      "type": "video",
      "video_id": "dQw4w9WgXcQ",
      "note": "Great intro to the topic, watch first",
      "added_date": "2025-06-02T08:00:00Z"
    },
    {
      "type": "video",
      "video_id": "abc123xyz",
      "note": "",
      "added_date": "2025-06-02T08:15:00Z"
    },
    {
      "type": "section_header",
      "text": "Advanced Topics",
      "id": "sec_002"
    }
  ]
}
```

### summary.json (per video)
```json
{
  "video_id": "dQw4w9WgXcQ",
  "generated_date": "2025-06-01T12:05:00Z",
  "model_used": "claude-sonnet-4-20250514",
  "summary_text": "This video covers...",
  "main_points": [
    {
      "point": "Introduction to the core concept",
      "detail": "The presenter explains that...",
      "start_time_seconds": 45,
      "end_time_seconds": 180
    }
  ]
}
```

---

## Keybindings Reference

| Context            | Key              | Action                                      |
|--------------------|------------------|---------------------------------------------|
| Global             | `Escape`         | Go back / exit current view                 |
| Global             | `q`              | Quit application                            |
| Global             | `Tab`            | Switch between "All" and "Collection" tabs  |
| Channel Select     | `↑↓`             | Navigate channel list                       |
| Channel Select     | `Enter`          | Select channel                              |
| Channel Select     | `a`              | Add new channel                             |
| Channel Select     | `r`              | Remove selected channel                     |
| Channel Select     | `s`              | Synchronize all channels                    |
| All Tab            | `↑↓`             | Navigate video list                         |
| All Tab            | `Enter`          | Open video in browser player                |
| All Tab            | `a`              | Add highlighted video to Collection         |
| All Tab            | `s`              | Synchronize current channel                 |
| All Tab            | `/`              | Search/filter videos                        |
| Collection Tab     | `↑↓`             | Navigate items                              |
| Collection Tab     | `Enter`          | Open video in browser player                |
| Collection Tab     | `Ctrl+↑`/`K`    | Move item up                                |
| Collection Tab     | `Ctrl+↓`/`J`    | Move item down                              |
| Collection Tab     | `h`              | Insert section header above current item    |
| Collection Tab     | `n`              | Add/edit note on current video              |
| Collection Tab     | `d` / `Delete`   | Remove item from collection                 |
| Sync Screen        | `Escape`         | Return (sync continues in background)       |

---

## Implementation Notes

### Error Handling
- Network failures during download should retry 3 times with exponential backoff
- If transcript is unavailable (no captions), mark `has_transcript: false` and skip summary; log a warning
- If Anthropic API call fails, mark `has_summary: false` and continue; retry on next sync
- Corrupted JSON files should be backed up and reinitialized with a warning to the user

### Performance
- Use asyncio for concurrent downloads (respect `max_concurrent_downloads` config)
- Textual's async workers for background sync while TUI remains responsive
- Lazy-load video list in TUI — don't read every summary into memory on startup, only on demand

### Security
- Anthropic API key read from environment variable (`ANTHROPIC_API_KEY`), never stored in config.json
- `config.json` stores only the env var name, not the key itself
- Temp HTML files created in system temp directory with restricted permissions

### Dependencies (requirements.txt)
```
textual>=0.50.0
rich>=13.0.0
yt-dlp>=2024.0.0
youtube-transcript-api>=0.6.0
anthropic>=0.40.0
click>=8.1.0
jinja2>=3.1.0
```

### Testing
- Use `pytest` for all tests
- Mock yt-dlp and Anthropic API calls in tests
- Test database read/write with temp directories
- Test TUI screens with Textual's `pilot` testing framework
- Test HTML generation by verifying template output contains expected elements

### Code Style
- Type hints on all function signatures
- Docstrings on all public functions and classes (Google style)
- Use `pathlib.Path` for all filesystem operations, never raw string paths
- Use `logging` module — never bare `print()` for status output
- All async operations use `asyncio` — no threads unless absolutely required by a library
- Constants in UPPER_SNAKE_CASE at module level
- Private methods prefixed with underscore

---

## AI Prompt Templates

### Video Summary System Prompt
```
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
}
```

### Master Summary System Prompt
```
You are a research synthesizer. Below are summaries of multiple videos from the same YouTube channel, ordered from newest to oldest.

Produce a master summary that:
1. Synthesizes the key themes and information across all videos
2. Organizes findings by topic/theme, not chronologically
3. Where information is contradictory between videos, note the contradiction and give higher weight to more recent videos (listed first)
4. Ignore any residual marketing or promotional content
5. Highlight any evolution of the creator's views or recommendations over time

Output clean, well-structured Markdown.
```

---

## First-Run Experience

On first launch when no `config.json` exists:
1. Create `~/TubeVault/` directory structure
2. Prompt user to add their first channel (URL or handle)
3. Ask if they want to sync now or later
4. Display brief keybinding help overlay (dismissible with any key)
5. Enter the library browser for the added channel
