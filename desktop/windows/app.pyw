"""Video Transcriptor desktop app for Windows (with the tool installed in WSL).

Starts the transcription server inside WSL in the background, shows it in a native
window (Microsoft Edge WebView2) and stops the server again when the window closes.
Installed by scripts/install-windows-app.sh, which writes config.json next to this file.
"""

import ctypes
import json
import subprocess
import threading
import time
import urllib.request
from pathlib import Path

import webview

HERE = Path(__file__).resolve().parent
CONFIG = json.loads((HERE / "config.json").read_text(encoding="utf-8"))
PORT = int(CONFIG.get("port", 8765))
URL = f"http://127.0.0.1:{PORT}"
DISTRO = CONFIG["distro"]
CREATE_NO_WINDOW = 0x08000000
LOG = HERE / "server.log"

LOADING_HTML = """
<html><body style="margin:0;height:100vh;display:flex;align-items:center;justify-content:center;
font-family:'Segoe UI',sans-serif;background:#f6f5f2;color:#6b6860">
<div style="text-align:center"><div style="width:28px;height:28px;margin:0 auto 14px;border:3px solid #e3e0d8;
border-top-color:#2f5bd3;border-radius:50%;animation:s .8s linear infinite"></div>Starting Video Transcriptor…</div>
<style>@keyframes s{to{transform:rotate(360deg)}}@media(prefers-color-scheme:dark){body{background:#151514!important;color:#9c998f!important}}</style>
</body></html>
"""


def server_up() -> bool:
    try:
        with urllib.request.urlopen(URL + "/api/options", timeout=1):
            return True
    except Exception:
        return False


def start_server() -> subprocess.Popen:
    cmd = ["wsl.exe", "-d", DISTRO, "--cd", CONFIG["repo"], "--",
           ".venv/bin/video-transcriptor", "serve", "--port", str(PORT), *CONFIG.get("serve_args", [])]
    log = open(LOG, "w", encoding="utf-8", errors="replace")
    return subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, creationflags=CREATE_NO_WINDOW)


def stop_server() -> None:
    subprocess.run(["wsl.exe", "-d", DISTRO, "--", "pkill", "-f", f"video-transcriptor serve --port {PORT}"],
                   creationflags=CREATE_NO_WINDOW, capture_output=True)


def set_window_icon() -> None:
    """Give the window and its taskbar button our icon instead of Python's."""
    user32 = ctypes.windll.user32
    user32.FindWindowW.restype = ctypes.c_void_p
    user32.LoadImageW.restype = ctypes.c_void_p
    user32.SendMessageW.argtypes = (ctypes.c_void_p, ctypes.c_uint, ctypes.c_size_t, ctypes.c_void_p)
    for _ in range(50):
        hwnd = user32.FindWindowW(None, "Video Transcriptor")
        if hwnd:
            break
        time.sleep(0.1)
    else:
        return
    for size, which in ((32, 1), (16, 0)):  # ICON_BIG = 1, ICON_SMALL = 0
        hicon = user32.LoadImageW(None, str(HERE / "icon.ico"), 1, size, size, 0x10)  # LR_LOADFROMFILE
        if hicon:
            user32.SendMessageW(hwnd, 0x80, which, hicon)  # WM_SETICON


def boot(window, state) -> None:
    try:
        set_window_icon()
    except Exception:
        pass
    if not server_up():
        state["proc"] = start_server()
        deadline = time.time() + 120
        while not server_up():
            if state["proc"].poll() is not None or time.time() > deadline:
                tail = LOG.read_text(encoding="utf-8", errors="replace")[-2000:] if LOG.exists() else ""
                window.load_html(
                    "<pre style='font-family:Consolas,monospace;padding:20px;white-space:pre-wrap'>"
                    "Video Transcriptor could not start.\n\n"
                    + tail.replace("&", "&amp;").replace("<", "&lt;") + "</pre>")
                return
            time.sleep(0.4)
    window.load_url(URL)


def main() -> None:
    # One window at a time: a second launch would stop the server under the first one.
    ctypes.windll.kernel32.CreateMutexW(None, False, "VideoTranscriptorDesktopApp")
    if ctypes.windll.kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
        ctypes.windll.user32.MessageBoxW(None, "Video Transcriptor is already open.", "Video Transcriptor", 0x40)
        return
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("VideoTranscriptor.App")

    webview.settings["ALLOW_DOWNLOADS"] = True
    state = {"proc": None}
    window = webview.create_window("Video Transcriptor", html=LOADING_HTML, width=1180, height=820,
                                   min_size=(720, 560), text_select=True)
    try:
        webview.start(boot, (window, state), private_mode=False)
    finally:
        stop_server()
        if state["proc"] and state["proc"].poll() is None:
            state["proc"].terminate()


if __name__ == "__main__":
    main()
