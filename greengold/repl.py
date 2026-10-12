"""`gg repl` and `gg run -e`: run snippets without writing a file.

The REPL keeps declarations (`fn`, `struct`, `enum`, `impl`, `const`, `import`, ...) and variable bindings,
and runs them again together with each new line, so a call with a side effect in an earlier binding runs
again. A bare expression is printed.
"""
from __future__ import annotations

import re
import sys
import tempfile
from pathlib import Path

_DECL = re.compile(r"^(fn|struct|enum|impl|feature|const|import|public|private|union|test|comptime|static|extern|type|async)\b")
_BIND = re.compile(r"^(fixed\s+)?[A-Za-z_]\w*\s*(:\s*[^=]+)?=(?!=)")
_STMT = re.compile(r"^(if|for|while|match|return|defer|print|panic|break|continue|loop|with|unsafe)\b")


def wrap(decls: list[str], body: list[str]) -> str:
    out = list(decls)
    out.append("fn main():")
    out += ["    " + ln for ln in body] or ["    pass"]
    return "\n".join(out) + "\n"


def _run_source(source: str, release: bool = False) -> int:
    from . import cli
    with tempfile.TemporaryDirectory(prefix="greengold_repl_") as tmp:
        f = Path(tmp) / "snippet.gg"
        f.write_text(source, encoding="utf-8")
        return cli.cmd_run([str(f)], release=release)


def run_snippet(code: str, release: bool = False) -> int:
    """`gg run -e CODE`: a full program (has `fn main`) runs as it is; otherwise the code is the body of `main`,
    and its last line is printed when it is a bare expression."""
    code = code.replace("\\n", "\n") if "\n" not in code and "\\n" in code else code
    if re.search(r"^fn main\b", code, re.M):
        return _run_source(code + "\n", release)
    decls: list[str] = []
    body: list[str] = []
    in_decl = False
    for ln in code.splitlines():
        if ln and not ln[0].isspace():
            in_decl = bool(_DECL.match(ln))
        (decls if in_decl else body).append(ln)
    if body and body[-1] and not body[-1][0].isspace() and not _is_statement(body[-1]):
        body[-1] = f"print({body[-1]})"
    return _run_source(wrap(decls, body), release)


def _is_statement(line: str) -> bool:
    s = line.strip()
    return not s or bool(_BIND.match(s) or _STMT.match(s) or s.startswith(("#", "pass")) or s.endswith(":")
                         or re.match(r"^[\w.\[\]]+\s*([-+*/%&|^]|<<|>>)=", s))


def repl(release: bool = False) -> int:
    from . import __version__
    print(f"Greengold {__version__} REPL. Blocks end with an empty line; :reset clears, :quit (or Ctrl-D) leaves.")
    decls: list[str] = []
    binds: list[str] = []
    while True:
        try:
            first = input("gg> ")
        except EOFError:
            print()
            return 0
        s = first.strip()
        if s in (":quit", ":q", "exit()"):
            return 0
        if s == ":reset":
            decls.clear()
            binds.clear()
            continue
        if not s:
            continue
        lines = [first]
        if first.rstrip().endswith(":"):
            while True:
                try:
                    more = input("... ")
                except EOFError:
                    break
                if not more.strip():
                    break
                lines.append(more)
        text = "\n".join(lines)
        if _DECL.match(s):
            trial = decls + [text]
            if _run_source(wrap(trial, []), release) == 0:
                decls = trial
            continue
        if _BIND.match(s) and len(lines) == 1:
            trial = binds + [text]
            if _run_source(wrap(decls, trial), release) == 0:
                binds = trial
            continue
        body = binds + (lines if _is_statement(s) or len(lines) > 1 else [f"print({s})"])
        _run_source(wrap(decls, body), release)
