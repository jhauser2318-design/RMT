"""Saving keys into the .env file from inside the app (⚙ → Live data)."""
import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV = ROOT / ".env"
EDITABLE = {"ALPACA_KEY_ID", "ALPACA_SECRET_KEY"}  # only these can be changed from the app


def save(values: dict[str, str]) -> None:
    """Write NAME=value lines into .env (replacing existing ones) and use them right away."""
    values = {k: v.strip() for k, v in values.items() if k in EDITABLE}
    for k, v in values.items():
        if not re.fullmatch(r"[A-Za-z0-9_\-+/=.]{0,200}", v):
            raise ValueError("That key has characters keys never contain. Copy it again from Alpaca.")
    source = ENV if ENV.is_file() else ROOT / ".env.example"
    lines = source.read_text(encoding="utf-8").splitlines() if source.is_file() else []
    done = set()
    for i, line in enumerate(lines):
        name = line.split("=", 1)[0].strip()
        if name in values:
            lines[i] = f"{name}={values[name]}"
            done.add(name)
    lines += [f"{k}={v}" for k, v in values.items() if k not in done]
    ENV.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.environ.update(values)
