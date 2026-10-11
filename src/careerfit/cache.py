"""Disk cache of judge answers. Composition-root code: it needs storage, so it stays out of judge/."""

import hashlib
import json
import os
import tempfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any


class CachingLLM:
    """Replays a stored answer when the exact same request was made before. Zero tokens."""

    def __init__(self, inner: Any, directory: Path):
        self.inner = inner
        self.directory = directory

    def create(self, **kwargs: Any) -> Any:
        key = hashlib.sha256(json.dumps(kwargs, sort_keys=True, default=_jsonable).encode()).hexdigest()
        path = self.directory / f"{key}.json"
        stored = _read(path)
        if stored is not None:
            return SimpleNamespace(stop_reason=stored["stop_reason"], model=stored["model"], content=stored["content"])
        response = self.inner.create(**kwargs)
        if getattr(response, "stop_reason", None) == "end_turn":
            text_blocks = [{"type": "text", "text": b.text} for b in response.content if getattr(b, "type", None) == "text"]
            entry = {"stop_reason": "end_turn", "model": getattr(response, "model", None), "content": text_blocks}
            try:
                _write_atomically(path, json.dumps(entry))
            except OSError:
                pass  # Best-effort: an unwritable cache must never discard a paid, completed answer.
        return response


def _read(path: Path) -> dict | None:
    """A missing, unreadable or malformed entry is a cache miss, never an error."""
    try:
        stored = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    if not isinstance(stored, dict) or stored.get("stop_reason") != "end_turn":
        return None
    if not isinstance(stored.get("model"), (str, type(None))) or "model" not in stored:
        return None
    content = stored.get("content")
    if not isinstance(content, list) or not all(
        isinstance(b, dict) and b.get("type") == "text" and isinstance(b.get("text"), str) for b in content
    ):
        return None
    return stored


def _write_atomically(path: Path, text: str) -> None:
    # Readers only ever see a complete file: write elsewhere in the same folder, then swap it in.
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _jsonable(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if isinstance(value, SimpleNamespace):
        return vars(value)
    return str(value)
