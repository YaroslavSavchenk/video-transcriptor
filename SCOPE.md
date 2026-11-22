# Scope

## Goal

A simple tool that turns a short video (Instagram Reel, YouTube Short, TikTok) into a text transcript. Videos are capped at **10 minutes**.

**Core principle: paste a link, get a transcript.** The user never downloads, saves or manages video files. The tool fetches only the audio stream behind the scenes, keeps it in a temporary location, and deletes it as soon as the transcript is done.

## In scope (v1)

- **Input**
  - A public video URL (Instagram Reels, YouTube / YouTube Shorts, TikTok; anything else yt-dlp supports is a bonus, not a promise).
  - A local video or audio file (secondary; the link is the main flow).
- **Duration limit**: reject videos longer than 10 minutes before downloading the full file (check metadata first).
- **Pipeline**
  1. Fetch metadata and check duration.
  2. **Captions first**: if the platform already has captions (YouTube, possibly TikTok), use those. No media is fetched at all.
  3. Otherwise fetch the **audio stream only** (no video) into a temporary directory and normalise it with ffmpeg (16 kHz mono).
  4. Transcribe locally with an open-source speech-to-text model (faster-whisper).
  5. Delete all temporary media automatically. Only the transcript remains.
- **Language**: **English is the primary target** (English-only models `small.en` / `distil-large-v3` by default). Other languages are supported via multilingual models (`large-v3-turbo`), chosen automatically when another language is selected.
- **Output formats**: plain text (`.txt`), subtitles (`.srt`, `.vtt`), and `.json` with timestamped segments.
- **Interface**: a **local web page** as the main interface. Run one command, open `http://localhost:8000`, paste a link, and the transcript appears on the page with *Copy* and *Download (.txt / .srt)* buttons and a language/model option. Runs entirely on your own machine.
- **Windows desktop app**: a native window (pywebview + Edge WebView2) with a Desktop/Start menu shortcut that starts and stops the server in WSL.
- **Saved transcripts**: every transcript is saved as `YYYY-MM-DD - <video name>.txt` (with title, link, date, language and source in a header) and listed in the app.
- **CLI** as a secondary interface for power users, e.g. `transcribe <url> [--format srt] [--lang nl] [--model small]`. Both share the same core.
- **Runs locally and for free**: no paid API or account needed; works on CPU, uses a GPU if one is available.
- **Cleanup**: temporary audio is always deleted, also when something fails. A `--keep-media` debug flag is the only exception.
- **Instagram login**: Reels often require a logged-in session. Support an optional `--cookies-from-browser <browser>` passthrough to yt-dlp.

## Out of scope (v1)

- Videos longer than 10 minutes.
- Private, login-only or DRM-protected content. Users can pass their own browser cookies to yt-dlp at their own risk; the tool doesn't help bypass access controls.
- Live streams.
- Translation, summarisation or other AI post-processing.
- Speaker diarisation (who said what).
- A hosted web service or mobile app.
- Bulk scraping of whole profiles or channels.

## Possible later additions

- Drag & drop local files in the web UI.
- Telegram bot or phone-friendly access over the local network.
- Speaker diarisation.
- Translation of the transcript to another language.
- Batch mode for a list of URLs.
- Optional hosted API backends (e.g. a free-tier Whisper API) for machines without enough compute.

## Planned stack

| Part | Choice |
| --- | --- |
| Language | Python 3.11+ |
| Download | [yt-dlp](https://github.com/yt-dlp/yt-dlp) |
| Audio decoding | PyAV (bundled ffmpeg libraries; no system ffmpeg needed) |
| Speech-to-text | [faster-whisper](https://github.com/SYSTRAN/faster-whisper) (Whisper models, CPU/GPU) |
| JS runtime for YouTube | [deno](https://pypi.org/project/deno/) (installed as a Python dependency) |
| Web UI | [FastAPI](https://fastapi.tiangolo.com/) + a single plain HTML page |
| CLI | `argparse` or `typer` |

The stack can still change based on research into existing tools.

## Success criteria

- A 60-second Reel or Short transcribes on an average laptop CPU in under a minute with the `small` model.
- English speech (and Dutch as a secondary language) comes out readable without manual fixes for clear audio.
- One command, no account or API key required.

## Legal note

Downloading content can conflict with a platform's terms of service and with copyright. The tool is meant for personal use, accessibility and research on content you're allowed to process. Users are responsible for how they use it.
