"""CloseAI: de-identify LLM chats locally before they ever reach a closed model."""

import os as _os
from pathlib import Path as _Path

__version__ = "0.1.0"


def _load_dotenv() -> None:
    """Tiny, dependency-free .env loader.

    Walks up from this file to find a `.env` and loads KEY=VALUE lines into the
    environment without overwriting anything already set in the real shell.
    Runs on import so `os.getenv(...)` in config.py just works.
    """

    for base in (_Path.cwd(), _Path(__file__).resolve().parent.parent):
        env_path = base / ".env"
        if not env_path.is_file():
            continue
        for raw in env_path.read_text().splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in _os.environ:
                _os.environ[key] = value
        break


_load_dotenv()
