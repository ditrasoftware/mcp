from __future__ import annotations

from pathlib import Path


def _read_version() -> str:
    version_file = Path(__file__).resolve().parent / "VERSION"
    return version_file.read_text(encoding="utf-8").strip()


__version__ = _read_version()
