# Scope

## Goal

A simple tool that turns a short video (Instagram Reel, YouTube Short, TikTok, or a local file) into a text transcript. Videos are capped at **10 minutes**.

## In scope (v1)

- **Input**
  - A public video URL (Instagram Reels, YouTube / YouTube Shorts, TikTok; anything else yt-dlp supports is a bonus, not a promise).
  - A local video or audio file.
- **Duration limit**: reject videos longer than 10 minutes before downloading the full file (check metadata first).
- **Pipeline**
  1. Fetch metadata and check duration.
  2. If the platform already offers captions, optionally use those (fast, no compute).
  3. Otherwise download audio only and normalise it with ffmpeg (16 kHz mono).
  4. Transcribe locally with an open-source speech-to-text model (Whisper family).
- **Language**: automatic language detection, with an option to force a language (e.g. `--lang nl`).
- **Output formats**: plain text (`.txt`), subtitles (`.srt`, `.vtt`), and `.json` with timestamped segments.
- **Interface**: a command-line tool, e.g. `transcribe <url-or-file> [--format srt] [--lang nl] [--model small]`.
- **Runs locally and for free**: no paid API or account needed; works on CPU, uses a GPU if one is available.
- **Cleanup**: temporary media files are deleted after transcription unless `--keep-media` is passed.

## Out of scope (v1)

- Videos longer than 10 minutes.
- Private, login-only or DRM-protected content. Users can pass their own browser cookies to yt-dlp at their own risk; the tool doesn't help bypass access controls.
- Live streams.
- Translation, summarisation or other AI post-processing.
- Speaker diarisation (who said what).
- A hosted web service or mobile app.
- Bulk scraping of whole profiles or channels.

## Possible later additions

- Simple local web UI (drag & drop a file or paste a URL).
- Speaker diarisation.
- Translation of the transcript to another language.
- Batch mode for a list of URLs.
- Optional hosted API backends (e.g. a free-tier Whisper API) for machines without enough compute.

## Planned stack

| Part | Choice |
| --- | --- |
| Language | Python 3.10+ |
| Download | [yt-dlp](https://github.com/yt-dlp/yt-dlp) |
| Audio processing | [ffmpeg](https://ffmpeg.org/) |
| Speech-to-text | [faster-whisper](https://github.com/SYSTRAN/faster-whisper) (Whisper models, CPU/GPU) |
| CLI | `argparse` or `typer` |

The stack can still change based on research into existing tools.

## Success criteria

- A 60-second Reel or Short transcribes on an average laptop CPU in under a minute with the `small` model.
- Dutch and English speech come out readable without manual fixes for clear audio.
- One command, no account or API key required.

## Legal note

Downloading content can conflict with a platform's terms of service and with copyright. The tool is meant for personal use, accessibility and research on content you're allowed to process. Users are responsible for how they use it.
