"""Keeps RMT up to date with the latest version on GitHub.

By default the launcher installs a newer version every time you open RMT,
like Life Control Center (turn it off under ⚙ → Updates; auto_enabled()).
The "Update now" button in ⚙ does the same on demand.

  1. check() asks GitHub which version is newest (one tiny request) and
     whether it's newer than the one installed,
  2. update() downloads it and copies it over, never touching your
     settings and keys (.env), your data (data/) or the Python
     environment (.venv).

If the RMT repository on GitHub is private, put a GitHub token with read
access in .env as GITHUB_TOKEN so the app can download it.
"""
import io
import json
import logging
import os
import shutil
import socket
import ssl
import stat
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from datetime import datetime
from pathlib import Path

REPO = "jhauser2318-design/RMT"
BRANCH = "main"

ROOT = Path(__file__).resolve().parent
VERSION_FILE = ROOT / "data" / "version.json"
KEEP = {".venv", "data", ".env", ".git"}   # never overwritten by an update
# Only used for the first install, so an update never touches them. (Antivirus programs
# often stop other programs from rewriting .bat / .ps1 files, which used to fail updates.)
INSTALL_ONLY = {"INSTALL.bat", "start.bat", "start.sh", "scripts"}
# Not needed to run RMT: if Windows won't let one be replaced, the update carries on without it.
OPTIONAL = {".github", "tests", "docs", "README.md", "LICENSE", ".gitattributes", ".gitignore", ".env.example"}
OLD_SUFFIX = ".rmt-old"  # files Windows wouldn't overwrite are moved aside with this, and removed next time
NO_WINDOW = 0x08000000 if os.name == "nt" else 0


def _token() -> str:
    return os.getenv("GITHUB_TOKEN", "").strip()


def _get(url: str, timeout: float = 15) -> bytes:
    headers = {"User-Agent": "RMT-updater", "Accept": "application/vnd.github+json"}
    if _token() and "api.github.com" in url:
        headers["Authorization"] = f"Bearer {_token()}"
    req = urllib.request.Request(url, headers=headers)
    # The computer's own certificates first; then Mozilla's list (certifi), which helps
    # on PCs whose certificate store Python can't read.
    contexts = [None]
    try:
        import certifi
        contexts.append(ssl.create_default_context(cafile=certifi.where()))
    except Exception:  # noqa: BLE001
        pass
    for i, ctx in enumerate(contexts):
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
                return resp.read()
        except urllib.error.URLError as e:
            if not isinstance(getattr(e, "reason", None), ssl.SSLError) or i == len(contexts) - 1:
                raise


def describe_error(e: Exception) -> str:
    reason = getattr(e, "reason", e)
    if isinstance(e, urllib.error.HTTPError):
        if e.code == 404:
            return ("GitHub couldn't find the RMT repository. If it's private, add a GITHUB_TOKEN "
                    "to the .env file (or make the repository public).")
        if e.code in (403, 429):
            return "GitHub is limiting requests from your network right now. Try again in an hour."
        return f"GitHub answered with an error ({e.code})."
    if isinstance(reason, (TimeoutError, socket.timeout)) or "timed out" in str(reason).lower():
        return "GitHub took too long to answer. Check your internet connection and try again."
    if isinstance(reason, socket.gaierror):
        return "Couldn't reach github.com. Check that you're connected to the internet."
    return f"Couldn't connect to GitHub ({reason})."


SETTINGS_FILE = ROOT / "data" / "settings.json"


def auto_enabled() -> bool:
    """Install new versions automatically when RMT opens (on unless turned off)."""
    try:
        return bool(json.loads(SETTINGS_FILE.read_text(encoding="utf-8")).get("auto_update", True))
    except Exception:  # noqa: BLE001 (no settings yet)
        return True


def set_auto(on: bool) -> None:
    try:
        data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        data = {}
    data["auto_update"] = bool(on)
    SETTINGS_FILE.parent.mkdir(exist_ok=True)
    SETTINGS_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def installed() -> dict:
    try:
        return json.loads(VERSION_FILE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def _latest() -> dict:
    data = json.loads(_get(f"https://api.github.com/repos/{REPO}/commits/{BRANCH}"))
    lines = [ln.strip() for ln in data["commit"]["message"].splitlines() if ln.strip()]
    if lines and lines[0].startswith("Merge pull request") and len(lines) > 1:
        lines = lines[1:]  # a merged pull request: its title is on the next line
    return {"sha": data["sha"], "summary": lines[0] if lines else "Latest version",
            "date": data["commit"]["committer"]["date"]}


def check() -> dict:
    """{"available": bool, "current": {...}, "latest": {...}, "error": str | None}"""
    current = installed()
    try:
        latest = _latest()
    except Exception as e:  # noqa: BLE001
        return {"available": False, "current": current, "latest": None, "error": describe_error(e)}
    return {"available": latest["sha"] != current.get("sha"), "current": current, "latest": latest, "error": None}


def _place(src: Path, dest: Path) -> None:
    """Copy src over dest, working around what Windows can throw at it."""
    try:
        shutil.copy2(src, dest)
        return
    except PermissionError:
        pass
    try:  # a read-only file: make it writable and try again
        os.chmod(dest, stat.S_IWRITE | stat.S_IREAD)
        shutil.copy2(src, dest)
        return
    except (PermissionError, FileNotFoundError):
        pass
    # In use or locked: Windows still lets you rename it, so move it aside and put the new one in place.
    aside = dest.with_name(f"{dest.name}{OLD_SUFFIX}{int(time.time())}")
    os.replace(dest, aside)
    try:
        shutil.copy2(src, dest)
    except OSError:
        os.replace(aside, dest)  # put the original back: never leave a file missing
        raise


def _clean_old() -> None:
    for old in ROOT.rglob(f"*{OLD_SUFFIX}*"):
        if ".venv" in old.parts:
            continue
        try:
            os.chmod(old, stat.S_IWRITE | stat.S_IREAD)
            old.unlink()
        except OSError:
            pass  # still in use: try again after the next update


def update() -> dict:
    """Install the newest version. {"updated": bool, "error": str | None, "summary": str}"""
    try:
        latest = _latest()
        if latest["sha"] == installed().get("sha"):
            return {"updated": False, "error": None, "summary": "You already have the latest version."}
        archive = _get(f"https://api.github.com/repos/{REPO}/zipball/{latest['sha']}", timeout=90)
    except Exception as e:  # noqa: BLE001
        return {"updated": False, "error": describe_error(e), "summary": ""}

    before = (ROOT / "requirements.txt").read_bytes() if (ROOT / "requirements.txt").is_file() else b""
    try:
        with tempfile.TemporaryDirectory() as tmp:
            zipfile.ZipFile(io.BytesIO(archive)).extractall(tmp)
            src = next(Path(tmp).iterdir())  # the ZIP holds one top-level folder
            _clean_old()
            skipped = []
            for path in sorted(src.rglob("*")):
                rel = path.relative_to(src)
                if rel.parts[0] in KEEP or rel.parts[0] in INSTALL_ONLY:
                    continue
                dest = ROOT / rel
                if path.is_dir():
                    dest.mkdir(parents=True, exist_ok=True)
                    continue
                try:
                    _place(path, dest)
                except OSError as e:
                    if rel.parts[0] not in OPTIONAL:
                        raise
                    skipped.append(str(rel))
                    logging.info("Update: left %s as it was (%s)", rel, e)
            if skipped:
                logging.warning("Update installed without these optional files: %s", ", ".join(skipped))
    except Exception as e:  # noqa: BLE001
        logging.warning("Update failed, keeping the current version (%s)", e)
        hint = (" Windows wouldn't let RMT replace one of its files; antivirus software can do this."
                " Closing RMT and opening it again usually fixes it.") if isinstance(e, PermissionError) else ""
        return {"updated": False, "error": f"The update couldn't be installed ({e}).{hint} The current version is still in place.", "summary": ""}

    if (ROOT / "requirements.txt").read_bytes() != before:
        python = Path(sys.executable).with_name("python.exe")
        if not python.is_file():
            python = Path(sys.executable)
        pip = subprocess.run([str(python), "-m", "pip", "install", "--quiet", "--disable-pip-version-check",
                              "-r", str(ROOT / "requirements.txt")], creationflags=NO_WINDOW, timeout=900,
                             capture_output=True, text=True)
        if pip.returncode != 0:
            logging.warning("Installing packages failed: %s", (pip.stderr or pip.stdout)[-1500:])

    VERSION_FILE.parent.mkdir(exist_ok=True)
    VERSION_FILE.write_text(json.dumps({**latest, "updated_at": datetime.now().isoformat(timespec="seconds")}, indent=2),
                            encoding="utf-8")
    logging.info("Updated to %s", latest["sha"][:7])
    return {"updated": True, "error": None, "summary": latest["summary"]}
