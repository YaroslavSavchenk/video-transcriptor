# Security policy

## Reporting a vulnerability

Please **don't open a public issue** for security problems. Report them privately through
[GitHub's private vulnerability reporting](https://github.com/YaroslavSavchenk/video-transcriptor/security/advisories/new).
You'll get a reply as soon as possible.

## Security model

video-transcriptor is a **single-user tool that runs on your own computer**.

- The web server listens on `127.0.0.1` only and has no login. It only answers requests addressed
  to `127.0.0.1`/`localhost` and rejects cross-site requests. This blocks DNS rebinding and
  CSRF attacks from websites open in your browser.
- Listening on another address (`--host`) exposes the tool, and the browser cookies it was
  started with, to everyone on that network. Only do this on a network you trust.
- `--cookies-from-browser` lets yt-dlp read that browser's cookies. They're only sent to the
  site the video comes from, but they belong to your account. Consider a separate account
  for Instagram.
- **Links are untrusted input.** Only https links to a single video on YouTube, Instagram or
  TikTok are accepted. Other sites, `file://`, local network addresses, `user:pass@`, custom
  ports, control characters and anything that isn't a plain link are rejected before anything
  is fetched. The `#fragment` is removed (yt-dlp can read hidden "smuggled" options from it), as
  are tracking and playlist parameters. yt-dlp itself is limited to the YouTube, Instagram and
  TikTok extractors, so a redirect can't send it to another site either.
- **Downloaded media is untrusted.** Audio is decoded in a separate Python process in isolated
  mode, with limits on memory (4 GB), CPU time, output size and run time. A damaged or hostile
  file makes that process fail, and the app then shows a normal error instead of crashing.
  Only audio is decoded, and size and length are capped.
- Titles, captions and error messages are always shown as plain text, never as HTML. Values
  written to transcript files are put on one line and sanitised so they can't change the file
  structure or create paths outside the transcripts folder.
- Nothing is ever passed to a shell. Subprocesses get argument lists.
- Media is downloaded to a private temporary folder (`0700`) and deleted after transcription.
- Dependencies are pinned in `uv.lock`, checked weekly with `pip-audit` in CI, and kept up to date
  by Dependabot.
