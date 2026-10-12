"""One-off migration: `name := value` -> `name = value` across the repository.

Greengold no longer has `:=`. A new variable is `name = value` (or `name: type = value`).

    python tools/convert_walrus.py [--dry-run]

* `.gg`   : replaced in code only; comments and string literals are left alone (and reported).
* `.py`   : replaced everywhere except real Python walrus operators (found with `tokenize`).
* `.md`, `.html`, `.txt` : plain text replacement.
"""
from __future__ import annotations

import io
import subprocess
import sys
import tokenize
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKIP_PY = {"greengold/lexer.py", "greengold/parser.py", "tools/convert_walrus.py"}
SKIP_PREFIX = ("_review", "benchmarks/reports", ".git/")


def convert_gg(text: str) -> tuple[str, list[int]]:
    out: list[str] = []
    in_string_hits: list[int] = []
    i, n, line = 0, len(text), 1
    while i < n:
        c = text[i]
        if c == "\n":
            line += 1
        if c == "#":
            j = text.find("\n", i)
            j = n if j < 0 else j
            out.append(text[i:j])
            i = j
            continue
        if c in "\"'":
            j = i + 1
            while j < n and text[j] != c and text[j] != "\n":
                j += 2 if text[j] == "\\" else 1
            seg = text[i:j + 1]
            if ":=" in seg:
                in_string_hits.append(line)
            out.append(seg)
            i = j + 1
            continue
        if text.startswith(":=", i):
            out.append("=")
            i += 2
            continue
        out.append(c)
        i += 1
    return "".join(out), in_string_hits


def convert_py(text: str) -> str:
    walrus: set[tuple[int, int]] = set()
    try:
        for tok in tokenize.generate_tokens(io.StringIO(text).readline):
            if tok.type == tokenize.OP and tok.string == ":=":
                walrus.add(tok.start)
    except (tokenize.TokenError, IndentationError):
        pass
    lines = text.split("\n")
    for ln, line in enumerate(lines, 1):
        res, k = [], 0
        while True:
            at = line.find(":=", k)
            if at < 0:
                res.append(line[k:])
                break
            res.append(line[k:at])
            res.append(":=" if (ln, at) in walrus else "=")
            k = at + 2
        lines[ln - 1] = "".join(res)
    return "\n".join(lines)


def main() -> int:
    dry = "--dry-run" in sys.argv
    files = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.splitlines()
    changed = 0
    for rel in files:
        if rel.startswith(SKIP_PREFIX) or rel in SKIP_PY:
            continue
        ext = Path(rel).suffix
        if ext not in (".gg", ".py", ".md", ".html", ".txt"):
            continue
        path = ROOT / rel
        raw = path.read_bytes()
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            continue
        if ":=" not in text:
            continue
        if ext == ".gg":
            new, hits = convert_gg(text)
            for h in hits:
                print(f"  string/char literal with := left alone: {rel}:{h}")
        elif ext == ".py":
            new = convert_py(text)
        else:
            new = text.replace(":=", "=")
        if new != text:
            changed += 1
            if not dry:
                path.write_bytes(new.encode("utf-8"))
    print(f"{'would change' if dry else 'changed'} {changed} files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
