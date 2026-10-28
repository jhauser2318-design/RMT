"""RMT - desktop launcher (Windows).

The Desktop icon runs this file with pythonw.exe (Python without a black
console window). It:
  1. opens RMT in its own window (Microsoft Edge or Google Chrome "app mode":
     no tabs or address bar, so it looks like a normal program), showing a
     "Starting..." screen,
  2. starts RMT's server quietly in the background; the window switches to
     the app as soon as it's ready,
  3. the server shuts itself down a few minutes after you close the window
     (the open window checks in every 15 seconds; when that stops, it's closed).

Updates, like Life Control Center: every time you open RMT it checks GitHub
and installs a newer version first, if there is one (see updater.py). You can
turn that off under ⚙ → Updates, and update with the "Update now" button
instead. After an update "launcher.pyw --restart" starts the new version
without opening a second window; the window that's already open switches to it.

If something goes wrong, details are written to data/app.log.
(start.bat still works too, and shows the server's messages in a window.)
"""
import json
import logging
import os
import socket
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PORT = 8050
URL = f"http://localhost:{PORT}"
DATA = ROOT / "data"
PROFILE = DATA / "browser-profile"  # the app window's own browser settings
LOG = DATA / "app.log"
SPLASH = ROOT / "frontend" / "splash.html"
LOCK_PORT = 47851  # held while a launcher is starting, so two clicks don't start two servers
NO_WINDOW = 0x08000000 if os.name == "nt" else 0  # Windows: don't flash a console
RESTART = "--restart" in sys.argv


def show_error(text: str) -> None:
    logging.error(text)
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, text, "RMT", 0x10)
    except Exception:
        print(text)


def server_info() -> dict | None:
    try:
        with urllib.request.urlopen(f"{URL}/api/app/info", timeout=2) as resp:
            return json.loads(resp.read())
    except Exception:
        return None


def find_browser() -> Path | None:
    """Edge comes with Windows; Chrome is the fallback."""
    places = []
    for var in ("ProgramFiles(x86)", "ProgramFiles", "LOCALAPPDATA"):
        base = os.environ.get(var)
        if base:
            places += [Path(base) / "Microsoft/Edge/Application/msedge.exe",
                       Path(base) / "Google/Chrome/Application/chrome.exe"]
    return next((p for p in places if p.is_file()), None)


def open_window(target: str) -> None:
    browser = find_browser()
    if browser is None:
        webbrowser.open(target)
        return
    subprocess.Popen([
        str(browser), f"--app={target}", f"--user-data-dir={PROFILE}",
        "--no-first-run", "--no-default-browser-check", "--window-size=1440,900",
    ])


def take_lock():
    lock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        lock.bind(("127.0.0.1", LOCK_PORT))
        return lock
    except OSError:
        lock.close()
        return None


def wait_until(check, seconds: float) -> bool:
    end = time.time() + seconds
    while time.time() < end:
        if check():
            return True
        time.sleep(0.4)
    return False


def start_server() -> subprocess.Popen:
    python = Path(sys.executable).with_name("pythonw.exe")
    if not python.is_file():
        python = Path(sys.executable)
    log = open(LOG, "a", encoding="utf-8")
    return subprocess.Popen(
        [str(python), "-m", "uvicorn", "backend.main:app", "--host", "127.0.0.1", "--port", str(PORT)],
        cwd=ROOT, stdout=log, stderr=log, creationflags=NO_WINDOW,
        env={**os.environ, "RMT_DESKTOP": "1"},  # the server stops itself once the window is closed
    )


def is_current(info: dict) -> bool:
    """Is the running server the same code as the files on disk?"""
    try:
        sys.path.insert(0, str(ROOT))
        import updater
        return info.get("code") == updater.code_fingerprint(ROOT)
    except Exception:  # noqa: BLE001 (can't tell: assume it's fine rather than stop it)
        return True


def stop_server(info: dict) -> None:
    pid = info.get("pid")
    if not pid:
        return
    try:
        import signal
        os.kill(int(pid), signal.SIGTERM)  # on Windows this ends the process
    except Exception as e:  # noqa: BLE001
        logging.warning("Couldn't stop the old RMT (pid %s): %s", pid, e)


def install_update() -> bool:
    """Automatic updates (on unless turned off in ⚙): install a newer version before starting."""
    try:
        sys.path.insert(0, str(ROOT))
        try:
            from dotenv import load_dotenv
            load_dotenv(ROOT / ".env")  # GITHUB_TOKEN, if the repository is private
        except ImportError:
            pass
        import updater
        if not updater.auto_enabled():
            return False
        result = updater.update()
    except Exception as e:  # noqa: BLE001 (never let an update problem stop RMT from opening)
        logging.warning("Automatic update skipped: %s", e)
        return False
    if result.get("error"):
        logging.info("Automatic update skipped: %s", result["error"])
    return bool(result.get("updated"))


def restart() -> None:
    python = Path(sys.executable).with_name("pythonw.exe")
    subprocess.Popen([str(python if python.is_file() else sys.executable), str(ROOT / "launcher.pyw"), "--restart"],
                     cwd=ROOT, creationflags=(0x00000008 | 0x00000200) if os.name == "nt" else 0,
                     start_new_session=os.name != "nt")


def main() -> None:
    DATA.mkdir(exist_ok=True)
    logging.basicConfig(filename=LOG, level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    info = server_info()
    if RESTART:  # after an update: wait for the old server to stop, start the new one
        wait_until(lambda: server_info() is None, 20)
    elif info:
        if is_current(info):  # already running this version: just open another window
            open_window(URL)
            return
        # An older RMT is still running (e.g. after reinstalling): stop it and start the new one.
        logging.info("Stopping an older RMT that's still running (pid %s)", info.get("pid"))
        stop_server(info)
        if not wait_until(lambda: server_info() is None, 15):
            show_error("An older copy of RMT is still running and couldn't be stopped.\n\n"
                       "Restart your computer, then open RMT again.")
            return

    lock = take_lock()
    if lock is None:  # another click is already starting RMT
        wait_until(server_info, 30)
        if not RESTART:
            open_window(URL)
        return

    if not RESTART:
        open_window(SPLASH.as_uri() if SPLASH.is_file() else URL)
        if install_update():  # a new version is in place: let its own launcher start it
            lock.close()
            restart()
            return
    logging.info("Starting RMT")
    proc = start_server()
    if not wait_until(lambda: server_info() is not None or proc.poll() is not None, 90) or proc.poll() is not None:
        show_error("RMT couldn't start. Details are in data\\app.log.\n\n"
                   "Try running start.bat to see what went wrong.")
    lock.close()


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # noqa: BLE001
        show_error(f"RMT couldn't start: {e}")
