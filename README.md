# video-transcriptor

Paste a link to an Instagram Reel, YouTube Short or TikTok and get the spoken text back. You don't download anything yourself. The tool fetches only the audio behind the scenes and deletes it right after transcribing.

Built mainly for **English** videos. Other languages (Dutch, German, …) work too.

## Features

- Local web page: paste a link, then copy or download the transcript
- Instagram Reels, YouTube videos and Shorts, TikTok, and other sites [yt-dlp](https://github.com/yt-dlp/yt-dlp) supports
- Videos up to 10 minutes
- Runs on your own computer and is free: no account or API key needed
- Uses the platform's own captions when they exist (YouTube), so nothing is downloaded and it takes about 2 seconds
- Otherwise runs local speech recognition with [faster-whisper](https://github.com/SYSTRAN/faster-whisper)
- Saves transcripts as `.txt`, `.srt`, `.vtt` or `.json` with timestamps
- Works on CPU, and uses an NVIDIA GPU when one is available

## Install

Requires Python 3.10+. Using [uv](https://docs.astral.sh/uv/) (or plain `pip`):

```bash
git clone https://github.com/YaroslavSavchenk/video-transcriptor.git
cd video-transcriptor
uv venv && uv pip install -e .
# Optional, for NVIDIA GPUs:
uv pip install -e ".[gpu]"
```

ffmpeg isn't required. Audio is decoded through PyAV, which ships with its own ffmpeg libraries.

## Use it

### Web page

```bash
.venv/bin/video-transcriptor serve
```

Open <http://127.0.0.1:8000>, paste a link and press **Transcribe**. The first time you use a model it downloads once (from about 250 MB up to 1.6 GB).

### Command line

```bash
# English YouTube Short to plain text
video-transcriptor transcribe https://www.youtube.com/shorts/VIDEO_ID

# Reel to SRT subtitles, saved to a file
video-transcriptor transcribe https://www.instagram.com/reel/REEL_ID/ -f srt -o reel.srt

# Dutch video (switches to the multilingual large-v3-turbo model automatically)
video-transcriptor transcribe https://www.tiktok.com/@user/video/ID --lang nl

# A local file with a specific model
video-transcriptor transcribe ./clip.mp4 -m distil-large-v3
```

Run `video-transcriptor transcribe --help` for all options.

### Models

| Model | Languages | Notes |
| --- | --- | --- |
| `small.en` (default) | English | Fast on any CPU |
| `distil-large-v3` | English | Better on hard audio; best with a GPU |
| `large-v3-turbo` | 99 languages | Default for non-English; best with a GPU |
| `tiny`, `base`, `small`, `medium`, `large-v3` | 99 languages | Trade speed for accuracy |

### Instagram and logins

Instagram often only serves a Reel's audio to logged-in users. If you get a "no sound track" or "login required" error, start the tool with the cookies of a browser where you're logged in:

```bash
video-transcriptor serve --cookies-from-browser firefox
# or export a cookies.txt file and use --cookies cookies.txt
```

**WSL users:** `--cookies-from-browser firefox` automatically finds your *Windows* Firefox profile. Chrome and Edge on Windows encrypt their cookies so they can't be read from WSL, so use Firefox or a `cookies.txt` export instead.

## How it works

1. Read the video's metadata and reject anything over 10 minutes.
2. If the platform has captions in the spoken language (e.g. YouTube), use them.
3. Otherwise fetch only the audio stream with yt-dlp into a temporary folder.
4. Transcribe it locally with faster-whisper (using voice-activity detection to skip music and silence).
5. Delete the temporary folder, even if something failed.

## Known limitations

- Platforms change often and can break downloading. Keep yt-dlp up to date with `uv pip install -U yt-dlp`.
- Some TikTok links currently fail inside yt-dlp ("Unexpected response from webpage request"). Updating yt-dlp usually fixes this.
- YouTube's automatic captions have no or weak punctuation. To get Whisper's output instead, untick "Use platform captions" or pass `--no-captions`.

## Development

```bash
uv pip install -e ".[dev]"
.venv/bin/pytest
```

See [SCOPE.md](SCOPE.md) for the scope and [docs/RESEARCH.md](docs/RESEARCH.md) for the research behind the choices.

## Responsible use

This tool downloads media from third-party platforms. That can conflict with their terms of service and with copyright law. Use it for content you have the right to process, such as your own videos, accessibility, or personal research. It doesn't bypass private accounts or DRM. You are responsible for how you use it.

## License

[MIT](LICENSE)
