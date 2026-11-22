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
- Media is downloaded to a private temporary folder (`0700`) and deleted after transcription.
- Dependencies are pinned in `uv.lock`, checked weekly with `pip-audit` in CI, and kept up to date
  by Dependabot.
