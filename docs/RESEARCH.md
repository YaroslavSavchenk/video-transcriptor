# Research: existing tools and free options

Snapshot from 2026-11-22. Stars and releases from the GitHub API, rounded.

## Existing open-source tools

| Project | License | Notes | Relevance |
| --- | --- | --- | --- |
| [transcribe-anything](https://github.com/zackees/transcribe-anything) | MIT | CLI: URL/file to Whisper, multiple backends. Active (v4.1.2, Sep 2026). | Closest existing match, worth studying |
| [AI-Video-Transcriber](https://github.com/wendy7756/AI-Video-Transcriber) | Apache-2.0 | Web app: yt-dlp, faster-whisper, LLM summary | Same stack, web UI |
| [reelscript](https://codeberg.org/xevrion/reelscript), clipscribe, transcribe-social | unverified | Reels/Shorts/TikTok via yt-dlp and faster-whisper | Directly relevant, maintenance unverified |
| [WhisperX](https://github.com/m-bain/whisperX) | BSD-2 | Word timestamps and speaker diarisation | Only if we need diarisation |
| [whisper.cpp](https://github.com/ggml-org/whisper.cpp) | MIT | C/C++ Whisper, best CPU and Apple Silicon performance | Alternative backend |
| [Buzz](https://github.com/chidiwilliams/buzz), [Vibe](https://github.com/thewh1teagle/vibe), [noScribe](https://github.com/kaixxx/noScribe) | MIT / MIT / GPL-3.0 | Desktop GUI apps | Alternatives for end users, not building blocks |
| [yt-whisper](https://github.com/m1guelpf/yt-whisper), [insanely-fast-whisper](https://github.com/Vaibhavs10/insanely-fast-whisper) | MIT / Apache-2.0 | Stale or GPU-only | Low |

## Building blocks

- **yt-dlp** (Unlicense): supports Instagram and TikTok. Instagram usually needs login cookies (`--cookies-from-browser firefox`). Extractors break often, so keep it up to date.
- **ffmpeg**: convert audio to 16 kHz mono.
- **faster-whisper** (MIT): the recommended default. Fast with int8 on CPU and supports 99 languages, including Dutch. Models: `large-v3-turbo` (best balance) and `small` (fast).
- **NVIDIA Parakeet-TDT-0.6B-v3** (CC-BY-4.0): 25 European languages including Dutch. ONNX builds run fast on CPU. A good optional backend.
- Not suitable: Distil-Whisper (mostly English-only), Moonshine (no Dutch).
- Not yet assessed: Cohere Transcribe, Qwen3-ASR, Voxtral Transcribe 2.

## Free captions without running speech-to-text

- **YouTube**: [youtube-transcript-api](https://github.com/jdepoix/youtube-transcript-api) or `yt-dlp --write-auto-subs`. Works from home IPs and is blocked from cloud IPs.
- **TikTok**: auto-captions may be exposed through yt-dlp (needs testing).
- **Instagram**: no reliable source, so expect to run speech-to-text.

## Free hosted APIs (optional backends)

- **Groq Whisper**: generous free tier (about 2,000 requests/day; numbers not confirmed on official pages). Needs an API key.
- **Deepgram**: $200 one-time credit. **AssemblyAI**: $50 one-time credit.
- **Hugging Face Inference**: no free credits anymore.

## Legal

TikTok, YouTube and Instagram all forbid automated downloading or scraping in their terms. Position the tool for personal, research and accessibility use. Using cookies can get the user's account rate-limited or banned.

## Recommended pipeline

1. Local file: go to step 3.
2. URL: try platform captions first (YouTube, TikTok). Otherwise download audio with `yt-dlp -x`.
3. Convert with ffmpeg to 16 kHz mono.
4. Transcribe with faster-whisper (auto-detect the language, or `--lang nl`).
5. Later: optional Groq or Parakeet backends.
