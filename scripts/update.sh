#!/usr/bin/env bash
# Update Video Transcriptor: latest code, dependencies (including yt-dlp, which needs
# frequent updates because platforms change), and the Windows desktop app if installed.
#
# Usage: scripts/update.sh
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO"

if [ -n "$(git status --porcelain --untracked-files=no)" ]; then
  echo "You have local changes in $REPO; commit or stash them first." >&2
  exit 1
fi

echo "→ Getting the latest version"
git checkout -q main
git pull -q --ff-only

echo "→ Updating dependencies"
EXTRAS=(--extra dev)
command -v nvidia-smi >/dev/null 2>&1 && EXTRAS+=(--extra gpu)
uv sync -q --locked "${EXTRAS[@]}"

if grep -qi microsoft /proc/sys/kernel/osrelease 2>/dev/null; then
  LOCALAPPDATA_WIN="$(cd /mnt/c && powershell.exe -NoProfile -NonInteractive -Command '$env:LOCALAPPDATA' | tr -d '\r')"
  if [ -d "$(wslpath -u "$LOCALAPPDATA_WIN\\VideoTranscriptor")" ]; then
    echo "→ Updating the Windows app"
    "$REPO/scripts/install-windows-app.sh" >/dev/null
  fi
fi

echo "✓ Up to date: $(git log -1 --format='%h %s')"
echo "  yt-dlp $(.venv/bin/python -c 'import yt_dlp; print(yt_dlp.version.__version__)')"
echo "  Restart Video Transcriptor if it's open."
