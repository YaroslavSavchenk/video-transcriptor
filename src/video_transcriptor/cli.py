from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from . import __version__, asr, formats


def _add_cookie_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--cookies-from-browser", metavar="BROWSER",
                   help="use the login cookies of this browser (e.g. firefox), needed for some Instagram Reels")
    p.add_argument("--cookies", metavar="FILE", help="Netscape cookies.txt file to use instead")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="video-transcriptor",
        description="Paste a link to a Reel, Short or TikTok and get a transcript.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    serve = sub.add_parser("serve", help="start the local web page")
    serve.add_argument("--host", default="127.0.0.1", help="address to listen on (default: 127.0.0.1)")
    serve.add_argument("--port", type=int, default=8000, help="port (default: 8000)")
    _add_cookie_args(serve)

    tr = sub.add_parser("transcribe", help="transcribe a link or local file on the command line")
    tr.add_argument("source", help="video link or path to a local file")
    tr.add_argument("-f", "--format", choices=formats.FORMATS, default="txt", help="output format (default: txt)")
    tr.add_argument("-l", "--lang", help="spoken language code, e.g. en or nl (default: English)")
    tr.add_argument("-m", "--model", choices=asr.MODELS, default=None,
                    help=f"speech recognition model (default: {asr.DEFAULT_MODEL} for English, "
                         f"{asr.DEFAULT_MULTILINGUAL_MODEL} for other languages)")
    tr.add_argument("-o", "--output", help="write to this file instead of the terminal")
    tr.add_argument("--no-captions", action="store_true",
                    help="always use speech recognition, even if the platform has captions")
    tr.add_argument("--device", choices=("auto", "cpu", "cuda"), default="auto")
    tr.add_argument("--keep-media", metavar="DIR", help="(debug) keep a copy of the fetched audio in DIR")
    _add_cookie_args(tr)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    if args.command == "serve":
        import uvicorn

        from .web import create_app

        app = create_app(args.cookies_from_browser, args.cookies)
        print(f"\n  Open http://{args.host}:{args.port} in your browser and paste a link.\n")
        uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
        return 0

    from .core import TranscriptionError, transcribe

    try:
        t = transcribe(
            args.source, language=args.lang, model=args.model, use_captions=not args.no_captions,
            device=args.device, cookies_from_browser=args.cookies_from_browser,
            cookies_file=args.cookies, keep_media_dir=args.keep_media,
        )
    except TranscriptionError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    out = formats.render(t, args.format)
    if args.output:
        Path(args.output).write_text(out, encoding="utf-8")
        print(f"Saved to {args.output} ({t.source}, language: {t.language})", file=sys.stderr)
    else:
        sys.stdout.write(out)
    return 0
