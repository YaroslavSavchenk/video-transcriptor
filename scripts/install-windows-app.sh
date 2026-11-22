#!/usr/bin/env bash
# Install Video Transcriptor as a Windows desktop app (run this inside WSL).
#
# - Copies the small launcher (desktop/windows/app.pyw) and icon to %LOCALAPPDATA%\VideoTranscriptor
# - Creates a Windows Python environment there with pywebview (uses Edge WebView2 for the window)
# - Adds "Video Transcriptor" shortcuts to the Desktop and the Start menu
#
# The transcription itself keeps running in WSL; the app starts it in the background
# when you open it and stops it when you close the window.
#
# Usage: scripts/install-windows-app.sh [extra 'serve' args, default: --cookies-from-browser firefox]
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PORT=8765
SERVE_ARGS=("$@")
[ ${#SERVE_ARGS[@]} -eq 0 ] && SERVE_ARGS=(--cookies-from-browser firefox)

if ! grep -qi microsoft /proc/sys/kernel/osrelease; then
  echo "This installer is for WSL on Windows." >&2; exit 1
fi
[ -x "$REPO/.venv/bin/video-transcriptor" ] || {
  echo "Install the tool first: cd $REPO && uv venv && uv pip install -e '.[gpu]'" >&2; exit 1; }

ps() { powershell.exe -NoProfile -NonInteractive -Command "$1" | tr -d '\r'; }

cd /mnt/c  # Windows programs complain when started from a Linux directory
LOCALAPPDATA_WIN="$(ps '$env:LOCALAPPDATA')"
APPDIR_WIN="$LOCALAPPDATA_WIN\\VideoTranscriptor"
APPDIR="$(wslpath -u "$APPDIR_WIN")"
UV_WIN="$(ps '(Get-Command uv -ErrorAction SilentlyContinue).Source')"
if [ -z "$UV_WIN" ]; then
  echo "uv for Windows is needed. Install it in PowerShell with: winget install astral-sh.uv" >&2; exit 1
fi
UV="$(wslpath -u "$UV_WIN")"

echo "→ Copying app files to $APPDIR_WIN"
mkdir -p "$APPDIR"
cp "$REPO/desktop/windows/app.pyw" "$REPO/desktop/icon.ico" "$APPDIR/"
python3 - "$APPDIR/config.json" "${WSL_DISTRO_NAME:?}" "$REPO" "$PORT" "${SERVE_ARGS[@]}" <<'EOF'
import json, sys
path, distro, repo, port, *args = sys.argv[1:]
json.dump({"distro": distro, "repo": repo, "port": int(port), "serve_args": args}, open(path, "w"), indent=2)
EOF

echo "→ Creating the Windows Python environment (first time takes a minute)"
"$UV" venv -q --allow-existing --python 3.12 "$APPDIR_WIN\\venv"
"$UV" pip install -q -U --python "$APPDIR_WIN\\venv\\Scripts\\python.exe" "pywebview>=5"

echo "→ Adding shortcuts"
ps "
\$shell = New-Object -ComObject WScript.Shell
\$targets = @([Environment]::GetFolderPath('Desktop'), (Join-Path ([Environment]::GetFolderPath('Programs')) ''))
foreach (\$dir in \$targets) {
  \$lnk = \$shell.CreateShortcut((Join-Path \$dir 'Video Transcriptor.lnk'))
  \$lnk.TargetPath = '$APPDIR_WIN\\venv\\Scripts\\pythonw.exe'
  \$lnk.Arguments = '\"$APPDIR_WIN\\app.pyw\"'
  \$lnk.WorkingDirectory = '$APPDIR_WIN'
  \$lnk.IconLocation = '$APPDIR_WIN\\icon.ico,0'
  \$lnk.Description = 'Paste a video link, get a transcript'
  \$lnk.Save()
}
"
echo "✓ Done. Open 'Video Transcriptor' from your Desktop or Start menu."
