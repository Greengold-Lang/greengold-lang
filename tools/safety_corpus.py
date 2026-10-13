"""Collects complete, single-file Greengold programs from the repository (examples, tests fixtures, and the
code blocks of the spec and the tutorial) as the seed corpus of the safety fuzzer."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BLOCK = re.compile(r"```gg\n(.*?)```", re.S)


def collect() -> dict[str, str]:
    out: dict[str, str] = {}
    for base in (ROOT / "examples", ROOT / "tests" / "fixtures" / "examples", ROOT / "eval"):
        if base.exists():
            for p in sorted(base.glob("*.gg")):
                out[f"file:{p.parent.name}/{p.name}"] = p.read_text(encoding="utf-8")
    for md in [ROOT / "docs" / "SPEC.md", ROOT / "README.md", *sorted((ROOT / "Learn").glob("*.md"))]:
        if not md.exists():
            continue
        for i, m in enumerate(BLOCK.finditer(md.read_text(encoding="utf-8"))):
            code = m.group(1)
            if re.search(r"^fn main\(", code, re.M):
                out[f"doc:{md.name}#{i}"] = code
    # Keep one copy of identical text.
    seen: set[str] = set()
    uniq: dict[str, str] = {}
    for k, v in out.items():
        if v not in seen:
            seen.add(v)
            uniq[k] = v
    return uniq


if __name__ == "__main__":
    c = collect()
    print(len(c), "programs")
