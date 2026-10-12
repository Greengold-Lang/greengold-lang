"""Language editions: how Greengold changes without breaking code that compiles today.

A package names its edition in gg.toml (`edition = "2026"`). Within an edition the language only grows:
new features, new library items, better diagnostics, and fixes for unsound rules. A change that would
stop correct code from compiling waits for the next edition, and `gg fix` migrates code to it. Packages
of different editions can be used together, because an edition only changes how its own files are read.
See docs/STABILITY.md.
"""
from __future__ import annotations

EDITIONS: dict[str, str] = {
    "2026": "the first edition: the language of docs/SPEC.md",
}
LATEST = "2026"

_active = LATEST


def check(name: str) -> str | None:
    """None when `name` is an edition this compiler knows, else the error message."""
    if name in EDITIONS:
        return None
    known = ", ".join(f'"{e}"' for e in EDITIONS)
    return f'unknown edition "{name}"; this compiler knows {known}'


def activate(name: str) -> None:
    global _active
    _active = name


def active() -> str:
    return _active


def at_least(name: str) -> bool:
    """Is the active edition `name` or newer? Edition-gated rules ask this."""
    return int(_active) >= int(name)
