"""Every complete `gg` example in README.md, docs/ and Learn/ type-checks.

A block is checked when it has `fn main`, no `...` placeholder, no `import "file"` of a sibling file,
and no comment marking an intentional compile error. A block may use declarations from earlier
blocks of the same file: those are prepended (without their `fn main`) when the block fails alone.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from greengold.cli import load_sources_and_ast
from greengold.typecheck import check_program

ROOT = Path(__file__).resolve().parents[1]
BLOCK = re.compile(r"```gg\r?\n(.*?)```", re.S)
ERROR_MARK = re.compile(r"COMPILE ERROR|ERROR!|<--|#\s*ERROR\b")
MAIN = re.compile(r"^fn main\(\):\n(?:(?:[ \t]+.*)?\n)*", re.M)
DOCS = [ROOT / "README.md", *sorted((ROOT / "docs").glob("*.md")), *sorted((ROOT / "Learn").glob("*.md"))]
DOCS = [d for d in DOCS if d.name != "SPEC.md"]  # SPEC has its own test (test_spec_api.py)


def _errors(src: str, tmp_path: Path) -> list[str]:
    path = tmp_path / "example.gg"
    path.write_text(src, encoding="utf-8")
    program, _, diags = load_sources_and_ast([str(path)])
    if not diags.has_errors():
        check_program(program, diags, str(path))
    return [d.message for d in diags.items if not d.hidden and d.severity == "error"]


def _checked(src: str) -> bool:
    return "fn main" in src and "..." not in src and 'import "' not in src and not ERROR_MARK.search(src)


@pytest.mark.parametrize("doc", DOCS, ids=lambda p: p.relative_to(ROOT).as_posix())
def test_doc_examples_typecheck(doc: Path, tmp_path: Path):
    blocks = [b.replace("\r\n", "\n") for b in BLOCK.findall(doc.read_text(encoding="utf-8"))]
    failures = []
    for index, src in enumerate(blocks):
        if not _checked(src):
            continue
        errs = _errors(src, tmp_path)
        if errs:
            context = "\n".join(MAIN.sub("", b) for b in blocks[:index] if 'import "' not in b)
            if not _errors(context + "\n" + src, tmp_path):
                continue
            failures.append(f"block {index}: {errs[0]}")
    assert not failures, "\n".join(failures)
