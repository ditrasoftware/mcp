from __future__ import annotations

"""Dev-only shim.

Historically this repo had two Prefab UI apps:
- `ferreromed_app.py`: the canonical "production" FerreroMed app provider
- `console.py`: a tool-by-tool console UI

Over time they converged and became redundant. To keep behavior consistent (and
avoid ChatGPT/MCP client confusion around multiple app providers + hashed tool
aliases), we keep a *single* app implementation and expose developer affordances
via a toggle inside that app.

This module remains as a compatibility shim for any local/dev code paths that
import `create_console_app`.
"""

from typing import Any

from .ferreromed_app import app as ferreromed_app
from .ferreromed_app import create_ferreromed_app


def create_console_app(*args: Any, **kwargs: Any):
    """Return the single canonical FerreroMed app.

    If called with (client, settings), this will initialize the underlying
    FerreroMed app via `create_ferreromed_app(client, settings)`.
    """

    if args or kwargs:
        return create_ferreromed_app(*args, **kwargs)
    return ferreromed_app
