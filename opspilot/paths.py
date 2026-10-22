"""Resolve read-only example data separately from writable runtime files."""
from __future__ import annotations

import os
from pathlib import Path


def bundled_data_dir() -> Path:
    """Example fixtures shipped in both source and wheel distributions."""
    return Path(__file__).resolve().parent / "resources" / "data"


def resolve_data_dir(directory: Path | None = None) -> Path:
    """Prefer explicit/custom data, then a checkout, then packaged examples.

    Explicit paths are never silently replaced by the examples when missing.
    """
    if directory is not None:
        return Path(directory).expanduser()
    configured = os.getenv("OPS_DATA_DIR")
    if configured:
        return Path(configured).expanduser()
    local = Path.cwd() / "data"
    return local if (local / "knowledge").is_dir() else bundled_data_dir()


def resolve_state_dir(directory: Path | None = None) -> Path:
    """Runtime state belongs to the caller's workspace, never package data."""
    if directory is not None:
        return Path(directory).expanduser()
    return Path(os.getenv("OPS_STATE_DIR") or "var").expanduser()
