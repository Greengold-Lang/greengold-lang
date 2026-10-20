"""Writes website/learn/content/stdlib.json, the data behind the standard library reference in the Learn app.

It is the same catalog as `gg api --json` and docs/API.md, grouped by module and trimmed to what the page shows, plus the
one-line summary at the top of each module's source file.

    python tools/build_learn_reference.py           # rewrite the file
    python tools/build_learn_reference.py --check   # exit 1 when it is out of date
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from greengold.api import library  # noqa: E402

OUT = ROOT / "website" / "learn" / "content" / "stdlib.json"
STD = ROOT / "greengold" / "std"
TITLES = {"builtin": "Compiler builtins", "core": "Core prelude"}


def summary(module: str) -> str:
    """The text after `# std.name:` on the first line of the module's source, or an empty string."""
    path = STD / (module.split(".", 1)[1] + ".gg") if module.startswith("std.") else None
    if path is None or not path.is_file():
        return ""
    first = path.read_text(encoding="utf-8").split("\n", 1)[0]
    m = re.match(r"#\s*" + re.escape(module) + r":\s*(.*)$", first)
    return m.group(1).strip() if m else ""


def render() -> str:
    doc = library()
    modules: dict[str, list[dict]] = {}
    for sym in doc["symbols"]:
        modules.setdefault(sym["module"], []).append(sym)
    out = {"modules": []}
    for name, syms in modules.items():
        out["modules"].append({
            "id": name,
            "title": TITLES.get(name, name),
            "summary": summary(name),
            "symbols": [{"k": s["kind"], "n": s["name"], "s": s["signature"], "d": s.get("description", "")} for s in syms],
        })
    return json.dumps(out, ensure_ascii=False, separators=(",", ":")) + "\n"


def main() -> int:
    text = render()
    if "--check" in sys.argv:
        current = OUT.read_text(encoding="utf-8") if OUT.exists() else ""
        if current != text:
            print(f"{OUT.relative_to(ROOT)} is out of date: run python tools/build_learn_reference.py", file=sys.stderr)
            return 1
        return 0
    OUT.write_text(text, encoding="utf-8", newline="\n")
    print("wrote", OUT.relative_to(ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
