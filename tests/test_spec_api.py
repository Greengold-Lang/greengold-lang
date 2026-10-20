"""The language spec's examples typecheck, and `gg api --json` lists the library."""
from __future__ import annotations

import json
import re
from pathlib import Path

from greengold.api import library
from greengold.cli import cmd_api, load_sources_and_ast
from greengold.typecheck import check_program

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "docs" / "SPEC.md"
BLOCK = re.compile(r"```gg\n(.*?)```", re.S)


def _blocks() -> list[str]:
    return BLOCK.findall(SPEC.read_text(encoding="utf-8"))


def test_spec_examples_typecheck(tmp_path):
    blocks = _blocks()
    assert len(blocks) >= 20
    failures = []
    for index, src in enumerate(blocks, 1):
        path = tmp_path / f"ex{index}.gg"
        path.write_text(src, encoding="utf-8")
        program, _, diags = load_sources_and_ast([str(path)])
        if not diags.has_errors():
            check_program(program, diags, str(path))
        if diags.has_errors():
            shown = "; ".join(d.message for d in diags.items if not d.hidden)
            failures.append(f"example {index}: {shown}")
    assert not failures, "\n".join(failures)


def test_api_json_lists_the_library(capsys):
    assert cmd_api(True) == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["schema_version"] == 1
    assert doc["tool"]["name"] == "gg"
    names = {(s["module"], s["name"]) for s in doc["symbols"]}
    for key in (
        ("builtin", "print"),
        ("builtin", "List"),
        ("core", "Optional"),
        ("core", "wrapping_add"),
        ("std.math", "sqrt"),
        ("std.thread", "Thread.spawn"),
    ):
        assert key in names
    for sym in doc["symbols"]:
        assert set(sym) == {"module", "name", "kind", "signature", "description", "no_std"}
        assert not sym["name"].startswith("_")
        assert sym["signature"]
    wrap = next(s for s in doc["symbols"] if s["name"] == "wrapping_add")
    assert "overflow: wrap" in wrap["signature"]
    assert library()["symbols"] == doc["symbols"]
