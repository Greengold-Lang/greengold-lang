"""Entry points for the browser playground (Pyodide). Every function takes and returns plain strings or JSON text.

Nothing here needs `llvmlite.binding`: only the front end runs (parse, type-check, fixes, format, explain).
"""
from __future__ import annotations

import contextlib
import io
import json
import os

FILE = os.environ.get("GG_WEB_FILE", "main.gg")  # relative: runtime errors name it `main.gg`


def _write(source: str) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(FILE)), exist_ok=True)
    with open(FILE, "w", encoding="utf-8", newline="\n") as f:
        f.write(source)


def check(source: str) -> str:
    """Diagnostics as JSON text: `{"ok", "text", "diagnostics": [...]}`; `text` is the terminal rendering."""
    import re
    source = source.lstrip("﻿")
    from . import cli
    cli._set_color("never")
    _write(source)
    require_main = bool(re.search(r"^fn main\(", source, re.M))
    _program, sources, diags, _checker = cli.analyze([FILE], overrides={FILE: source}, require_main=require_main)
    cli.prepare(diags.items)
    cli.verify_fixes(diags.items, sources, FILE, require_main=require_main)
    from .diagnostics import export_json, reset_prepared
    reset_prepared(diags.items)
    doc = export_json(diags.items, sources, FILE, "check", source)
    buf = io.StringIO()
    if not doc["ok"]:
        with contextlib.redirect_stderr(buf):
            cli._print_diagnostics(diags.items, source, FILE, sources)
    doc["text"] = buf.getvalue().replace(FILE, "main.gg")
    return json.dumps(doc)


def build(source: str, release: bool = False) -> str:
    """LLVM IR for `wasm32-wasi` as JSON text: `{"ok": true, "ir": ...}`, or `{"ok": false, "text": ...}` with the
    diagnostics (or the code generator's complaint) as the terminal shows them."""
    from . import cli
    from .codegen_llvm import CodegenError
    cli._set_color("never")
    source = source.lstrip("﻿")
    _write(source)
    buf = io.StringIO()
    try:
        program, sources, diags, _checker = cli.analyze([FILE], overrides={FILE: source})
        if diags.has_errors():
            cli.prepare(diags.items)
            with contextlib.redirect_stderr(buf):
                cli._print_diagnostics(diags.items, source, FILE, sources)
            return json.dumps({"ok": False, "text": buf.getvalue().replace(FILE, "main.gg")})
        ir_text = cli._gen_llvm(program, FILE, release, False, "wasm32-wasi", False)
    except CodegenError as err:
        return json.dumps({"ok": False, "text": f"Error: {err}".replace(FILE, "main.gg")})
    return json.dumps({"ok": True, "ir": ir_text})


def fix(source: str, likely: bool = False) -> str:
    """JSON text `{"source", "applied": [{"line", "description"}]}` after applying every verified fix."""
    from . import cli
    _write(source)
    new, applied, _remaining = cli.fix_source(source, FILE, likely)
    return json.dumps({"source": new, "applied": [{"line": ln, "description": d} for ln, d in applied]})


def format(source: str) -> str:  # noqa: A001 - the name the page calls
    from .fmt import format_source
    return format_source(source)


def explain(code: str) -> str:
    from . import cli
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        cli.cmd_explain(code, False)
    return buf.getvalue()


def version() -> str:
    from . import __version__
    return __version__
