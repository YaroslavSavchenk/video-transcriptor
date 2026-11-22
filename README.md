# video-transcriptor

Paste a link to an Instagram Reel, YouTube Short or TikTok and get the spoken text back. No need to download anything yourself: the tool fetches only the audio behind the scenes and deletes it right after transcribing.

> **Status:** early development. Nothing is installable yet. See [SCOPE.md](SCOPE.md) for what's planned.

## Features (planned)

- Transcribe from a URL (Instagram Reels, YouTube / Shorts, TikTok) or a local video/audio file
- Videos up to 10 minutes
- Runs locally and for free: no account or API key needed
- Automatic language detection, or force one with `--lang` (e.g. Dutch, English)
- Output as `.txt`, `.srt`, `.vtt` or `.json` with timestamps
- Uses existing platform captions when available (nothing gets fetched), otherwise local speech-to-text
- Temporary audio is deleted automatically; only the transcript is kept
- Works on CPU, uses a GPU when available

## How it works

1. Check the video's metadata and reject anything over 10 minutes.
2. If the platform has captions (e.g. YouTube), use them directly.
3. Otherwise fetch only the audio stream with [yt-dlp](https://github.com/yt-dlp/yt-dlp) into a temporary folder and convert it to 16 kHz mono with [ffmpeg](https://ffmpeg.org/).
4. Transcribe it with [faster-whisper](https://github.com/SYSTRAN/faster-whisper), an efficient implementation of OpenAI's Whisper models.
5. Delete the temporary audio and write the transcript in the format you asked for.

## Planned usage

```bash
# Transcribe a YouTube Short to plain text
transcribe https://www.youtube.com/shorts/VIDEO_ID

# Dutch Instagram Reel to SRT subtitles
transcribe https://www.instagram.com/reel/REEL_ID/ --lang nl --format srt

# A local file with a larger model
transcribe ./clip.mp4 --model medium --format json
```

## Requirements (planned)

- Python 3.10+
- ffmpeg installed and on your `PATH`

## Responsible use

This tool downloads media from third-party platforms. That can conflict with their terms of service and with copyright law. Use it for content you have the right to process, such as your own videos, accessibility, or personal research. It does not bypass logins, private accounts or DRM. You are responsible for how you use it.

## Contributing

Issues and pull requests are welcome. For larger changes, open an issue first so we can discuss the approach.

## License

[MIT](LICENSE)
