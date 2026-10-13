"""Shrinks a program that the safety oracle flags: removes statements of `main` (and of other functions) while the
verdict stays the same.

    python tools/safety_min.py finding.gg [--kind double_free] [--out smaller.gg]
"""
from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

import fuzz_safety as FS  # noqa: E402
import safety_oracle as O  # noqa: E402


def verdict_kind(src: str, work: Path) -> str:
    ok, _ = O.accepted(src)
    if not ok:
        return "rejected"
    v = O.check_program(src, work)
    if v.kind == "ok" and v.live:
        return "leak"
    if v.kind == "ok":
        import re
        m = re.search(rb"GG_LIVE (-?\d+)", v.stdout_leak)
        if m and int(m.group(1)) != 0:
            return "live_count"
    return v.kind


def minimize(src: str, kind: str, work: Path, only_main: bool = False) -> str:
    lines = src.rstrip("\n").split("\n")
    changed = True
    while changed:
        changed = False
        fns = FS.functions(lines)
        if only_main:
            fns = [f for f in fns if lines[f[0] - 1].lstrip().startswith("fn main")]
        # try the biggest blocks first
        cand = []
        for f in fns:
            for i in FS.statements(lines, f):
                cand.append((FS.block_end(lines, i) - i, i))
        cand.sort(reverse=True)
        for _, i in cand:
            e = FS.block_end(lines, i)
            new = lines[:i] + lines[e:]
            if not any(l.strip() for l in new[i - 1:i + 1]) and False:
                continue
            text = "\n".join(new) + "\n"
            if verdict_kind(text, work) == kind:
                lines = new
                changed = True
                break
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("file")
    ap.add_argument("--kind", default="")
    ap.add_argument("--out", default="")
    ap.add_argument("--only-main", action="store_true")
    a = ap.parse_args()
    src = Path(a.file).read_text(encoding="utf-8")
    work = Path(tempfile.mkdtemp(prefix="ggmin_"))
    kind = a.kind or verdict_kind(src, work)
    print("kind:", kind, file=sys.stderr)
    out = minimize(src, kind, work, a.only_main)
    if a.out:
        Path(a.out).write_text(out, encoding="utf-8")
    else:
        print(out)


if __name__ == "__main__":
    main()
