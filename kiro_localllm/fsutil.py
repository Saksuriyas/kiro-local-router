"""Filesystem helpers. Every path is confined to the workspace root."""
from __future__ import annotations

import os
from pathlib import Path

from .config import env, env_int


class ToolError(RuntimeError):
    """Expected, user-facing failure. Returned to the agent as 'ERROR: ...'."""


def root() -> Path:
    return Path(env("WORKSPACE_ROOT") or os.getcwd()).expanduser().resolve()


def _inside(path: Path) -> Path:
    base = root()
    try:
        path.relative_to(base)
    except ValueError:
        raise ToolError(
            f"path '{path}' is outside the workspace root '{base}'. "
            "Use a path inside the project, or set WORKSPACE_ROOT."
        )
    return path


def _resolve(p: str) -> Path:
    candidate = Path(p).expanduser()
    if not candidate.is_absolute():
        candidate = root() / candidate
    return _inside(candidate.resolve())


def check_inside(p: str) -> str:
    """Validate a path without requiring it to exist; return it relative to root."""
    return str(_resolve(p).relative_to(root()))


def read_text(p: str) -> str:
    path = _resolve(p)
    if not path.is_file():
        raise ToolError(f"file not found: {p}")
    limit = env_int("MAX_FILE_BYTES", 1_000_000)
    if path.stat().st_size > limit:
        raise ToolError(f"file too large (> {limit} bytes): {p}")
    return path.read_text(encoding="utf-8", errors="ignore")


def write_text(p: str, content: str, overwrite: bool) -> Path:
    path = _resolve(p)
    parts = {part.lower() for part in path.relative_to(root()).parts}
    if ".git" in parts or path.name.lower().startswith(".env"):
        raise ToolError(f"refusing to write to a protected path: {p}")
    if path.exists() and not overwrite:
        raise ToolError(f"output already exists: {p}. Call again with overwrite=true to replace it.")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.rstrip() + "\n", encoding="utf-8")
    return path
