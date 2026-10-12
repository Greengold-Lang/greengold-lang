"""Shared helpers for tests: passes source through lexer -> parser -> typecheck pipeline."""
from greengold.diagnostics import DiagnosticBag
from greengold.lexer import tokenize
from greengold.parser import parse
from greengold.typecheck import check_program

PREAMBLE = """\
struct Counter:
    value: i32

fn show(c: Counter):
    print(c.value)

fn bump(c: lend Counter):
    c.value += 1

fn finish(c: consume Counter):
    print(c.value)

"""


def front_end(src: str):
    """Returns (program, diagnostics)."""
    diags = DiagnosticBag()
    tokens = tokenize(src, diags)
    if diags.has_errors():
        return None, diags.items
    program = parse(tokens, diags)
    if diags.has_errors():
        return program, diags.items
    check_program(program, diags)
    return program, diags.items


def messages(src: str) -> list[str]:
    return [d.message for d in front_end(src)[1]]


def with_main(body: str, preamble: str = PREAMBLE) -> str:
    lines = "".join(f"    {l}\n" if l.strip() else "\n" for l in body.strip("\n").splitlines())
    return preamble + "fn main():\n" + lines


# --- v2 helpers: end-to-end execution ------------------------------------
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# Tests read their own copy of the examples, so edits to examples/ cannot break them.
EXAMPLES_DIR = ROOT / "tests" / "fixtures" / "examples"
HAS_CC = shutil.which("gcc") is not None or shutil.which("clang") is not None


def run_gg_source(tmp_path: Path, src: str, release: bool = False):
    """Compiles and runs source with `python -m greengold run` (returns CompletedProcess)."""
    f = tmp_path / "a.gg"
    f.write_text(src, encoding="utf-8")
    cmd = [sys.executable, "-m", "greengold", "run", str(f)] + (["--release"] if release else [])
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", cwd=ROOT, timeout=120)


def run_example(name: str, release: bool = False):
    cmd = [sys.executable, "-m", "greengold", "run", str(EXAMPLES_DIR / name)] + (["--release"] if release else [])
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", cwd=ROOT, timeout=120)


def run_built(src: str, release: bool = False, filename: str = "main.gg", unchecked: bool = False,
              extra_c: str = "", timeout: int = 10, stdin: str | None = None) -> subprocess.CompletedProcess:
    """Builds source in-process with the LLVM backend and runs the executable.
    `extra_c` is compiled with gcc/clang and linked in (for extern tests)."""
    import tempfile
    from greengold.cli import build_source
    with tempfile.TemporaryDirectory() as td:
        exe = Path(td) / ("test.exe" if sys.platform == "win32" else "test")
        links = []
        if extra_c:
            cc = shutil.which("gcc") or shutil.which("clang")
            c_file, o_file = Path(td) / "extra.c", Path(td) / "extra.o"
            c_file.write_text(extra_c, encoding="utf-8")
            res = subprocess.run([cc, "-c", str(c_file), "-o", str(o_file)], capture_output=True, text=True)
            assert res.returncode == 0, res.stderr
            links.append(str(o_file))
        code = build_source(src, exe, filename=filename, release=release, unchecked=unchecked, links=links)
        assert code == 0, f"build failed with code {code}"
        return subprocess.run([str(exe)], capture_output=True, text=True, encoding="utf-8", timeout=timeout,
                              input=stdin)
