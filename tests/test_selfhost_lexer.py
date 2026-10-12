"""self-hosting step 1 - the Greengold lexer (selfhost/lexer.gg) must agree with greengold/lexer.py."""
import subprocess
import sys
from pathlib import Path

import pytest

from greengold.diagnostics import DiagnosticBag
from greengold.lexer import tokenize
from tests.helpers import ROOT, EXAMPLES_DIR

LEXER_SRC = ROOT / "selfhost" / "lexer.gg"


def py_tokens(text: str) -> list[str]:
    diags = DiagnosticBag()
    toks = tokenize(text, diags)
    assert not diags.has_errors()
    out = []
    for t in toks:
        txt = t.text.replace("\\", "\\\\").replace("\n", "\\n").replace("\t", "\\t").replace("\r", "\\r")
        out.append(f"{t.line}:{t.col}:{t.length} {t.kind} {txt}")
    return out


def corpus() -> list[Path]:
    files = sorted((EXAMPLES_DIR).glob("*.gg")) + sorted((ROOT / "greengold" / "std").glob("*.gg"))
    files += [LEXER_SRC, ROOT / "greengold" / "core" / "core.gg"]
    good = []
    for f in files:
        text = f.read_text(encoding="utf-8")
        if not text.isascii() or "\t" in text:
            continue
        diags = DiagnosticBag()
        tokenize(text, diags)
        if not diags.has_errors():
            good.append(f)
    return good


@pytest.fixture(scope="module")
def lexer_exe(tmp_path_factory):
    exe = tmp_path_factory.mktemp("selfhost") / ("lexer" + (".exe" if sys.platform == "win32" else ""))
    r = subprocess.run([sys.executable, "-m", "greengold", "build", str(LEXER_SRC), "-o", str(exe)],
                       capture_output=True, text=True, encoding="utf-8", cwd=ROOT, timeout=300)
    assert r.returncode == 0, r.stderr
    return exe


def run_selfhost(exe: Path, text: str, tmp: Path) -> subprocess.CompletedProcess:
    (tmp / "gg_selfhost_in.txt").write_bytes(text.encode("utf-8"))
    return subprocess.run([str(exe)], capture_output=True, cwd=tmp, timeout=120)


def test_corpus_is_not_trivial():
    assert len(corpus()) >= 20


def test_lexer_matches_python_on_corpus(lexer_exe, tmp_path):
    mismatches = []
    for f in corpus():
        text = f.read_text(encoding="utf-8").replace("\r\n", "\n")
        r = run_selfhost(lexer_exe, text, tmp_path)
        got = r.stdout.decode("utf-8").splitlines()
        if r.returncode != 0 or got != py_tokens(text):
            mismatches.append(f.name)
    assert not mismatches, mismatches


def test_lexer_reports_error_status(lexer_exe, tmp_path):
    r = run_selfhost(lexer_exe, 'fn main():\n    x = "oops\n', tmp_path)
    assert r.returncode == 1
    assert b"LEX ERROR" in r.stdout
    assert b"GG0110" in r.stdout


def py_dump(text: str) -> list[str]:
    diags = DiagnosticBag()
    toks = tokenize(text, diags)
    out = []
    for t in toks:
        txt = t.text.replace("\\", "\\\\").replace("\n", "\\n").replace("\t", "\\t").replace("\r", "\\r")
        out.append(f"{t.line}:{t.col}:{t.length} {t.kind} {txt}")
    if not diags.items:
        return out
    out.append("LEX ERROR")
    for e in diags.items:
        out.append(f"DIAG {e.code} {e.line} {e.col} {e.length} {e.message}")
        if e.hint:
            out.append(f"HINT {e.hint}")
        for fix in e.fixes:
            for ed in fix.edits:
                out.append(
                    f"FIX {fix.applicability}|{fix.description}|{ed.start_line}:{ed.start_col}:{ed.end_line}:{ed.end_col}|{ed.replacement}"
                )
    return out


DIAG_CASES = [
    "x = 5\n",
    "fn f():\n    return\n",
    'f"ab"\n',
    '"""ab"""\n',
    'f"""ab\ncd"""\n',
    "1_000\n",
    "0x10\n",
    "0b1010\n",
    "1.50\n",
    "1_0.5\n",
    '"a\\nb"\n',
    "'A'\n",
    "'\\n'\n",
    "fn f():\n\treturn\n",
    "x = 5 // c\n",
    "fn f():\n  return\n",
    "x = P{ a: 1\n",
    "fn f():\n    if x:\n        return",
    "'é'\n",
    'fn main():\n    x = "oops\n',
    "0..n\n",
    "0..=10\n",
    "hot fn f():\n    return\n",
    "007\n",
    "0x1_0\n",
    "99999999999999999999\n",
    "''\n",
    "'ab'\n",
    '"\\q"\n',
    "'\\q'\n",
    '"\\0"\n',
    "0x\n",
    "0b\n",
    "1a\n",
    "fn f():\n    return\n  x = 1\n",
    "x = 1 }\n",
    "x = (1}\n",
    "f\"oops\n",
    "fn f():\n    return\nelse:\n    return\n",
    "$\"ab\"\n",
    "'\\0'\n",
]


def test_lexer_diagnostics_match_python(lexer_exe, tmp_path):
    mismatches = []
    for src in DIAG_CASES:
        r = run_selfhost(lexer_exe, src, tmp_path)
        got = r.stdout.decode("utf-8").splitlines()
        expect = py_dump(src)
        bad_code = (r.returncode != 0) if not any(line.startswith("DIAG ") for line in expect) else (r.returncode == 0)
        if got != expect or bad_code:
            mismatches.append((src, expect, got, r.returncode))
    assert not mismatches, mismatches[0]


def test_lexer_lexes_itself(lexer_exe, tmp_path):
    text = LEXER_SRC.read_text(encoding="utf-8").replace("\r\n", "\n")
    r = run_selfhost(lexer_exe, text, tmp_path)
    assert r.stdout.decode("utf-8").splitlines() == py_tokens(text)
