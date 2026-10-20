"""Project tooling: gg.toml manifest, `gg new`, `gg fmt`, `gg test`, `gg doc`, incremental build cache."""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib
from dataclasses import dataclass, field
from pathlib import Path

MANIFEST = "gg.toml"


# -- manifest -------------------------------------------------------------------------------------

@dataclass
class Manifest:
    root: Path
    name: str
    version: str
    main: Path
    deps: dict[str, Path] = field(default_factory=dict)  # dependency name -> directory searched for imports
    edition: str = "2026"  # language edition (see greengold/editions.py)
    native: object = None  # native.Native: C/C++ sources of the package and its dependencies


def find_manifest(start: Path | None = None) -> Path | None:
    cur = (start or Path.cwd()).resolve()
    for d in [cur, *cur.parents]:
        if (d / MANIFEST).is_file():
            return d / MANIFEST
    return None


def load_manifest(path: Path, _seen: set[Path] | None = None) -> Manifest:
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    pkg = data.get("package", {})
    if "name" not in pkg:
        raise ValueError(f"{path}: [package] name is required")
    root = path.parent.resolve()
    from .packages import PackageError, resolve
    try:
        deps = resolve(root) if data.get("dependencies") else {}
    except PackageError as err:
        raise ValueError(f"{path}: {err}") from None
    from . import editions
    edition = str(pkg.get("edition", editions.LATEST))
    problem = editions.check(edition)
    if problem:
        raise ValueError(f"{path}: {problem}")
    from .native import Native, NativeError, read as read_native
    native = Native()
    try:
        read_native(root, native)
        for src in deps.values():
            read_native(src.parent if src.name == "src" and (src.parent / MANIFEST).is_file() else src, native)
    except NativeError as err:
        raise ValueError(str(err)) from None
    return Manifest(root=root, name=pkg["name"], version=str(pkg.get("version", "0.1.0")),
                    main=root / pkg.get("main", "src/main.gg"), deps=deps, edition=edition, native=native)


def activate_manifest(m: Manifest) -> None:
    """Registers the dependency roots used by import resolution."""
    from . import cli, editions
    cli.DEP_ROOTS.clear()
    cli.DEP_ROOTS.update(m.deps)
    cli.NATIVE = m.native
    editions.activate(m.edition)


_TEMPLATES = {
    "bin": ('fn test_math():\n    if 1 + 1 != 2:\n        panic("math is broken")\n\n'
            'fn main():\n    print("Hello from @NAME@!")\n'),
    "lib": ('public\n# Adds two numbers.\nfn add(a: i32, b: i32) -> i32:\n    return a + b\n\nprivate\n'
            'fn test_add():\n    require add(2, 3) == 5\n\n'
            'fn main():\n    print("@NAME@: run `gg test` to check the library")\n'),
    "cli": ('import std.process\n\n'
            'fn main():\n    argv = process.args()\n'
            '    if argv.len < 2:\n        print("usage: @NAME@ <name>")\n        return\n'
            '    print(f"Hello, {argv[1]}!")\n'),
}


def _write_cortex_m(root: Path, name: str) -> None:
    from . import templates
    (root / "src" / "main.gg").write_text(templates.CORTEX_M_MAIN, encoding="utf-8", newline="\n")
    (root / "link.ld").write_text(templates.CORTEX_M_LINK, encoding="utf-8", newline="\n")
    (root / "README.md").write_text(templates.CORTEX_M_README.replace("@NAME@", name), encoding="utf-8", newline="\n")


def cmd_new(name: str, path: str | None = None, template: str = "bin") -> int:
    root = Path(path or name)
    if root.exists() and any(root.iterdir()):
        print(f"Error: `{root}` already exists and is not empty.", file=sys.stderr)
        return 1
    (root / "src").mkdir(parents=True, exist_ok=True)
    (root / MANIFEST).write_text(
        f'[package]\nname = "{name}"\nversion = "0.1.0"\nedition = "2026"\nmain = "src/main.gg"\n\n[dependencies]\n'
        '# mylib = { path = "../mylib" }   # then: import mylib.module\n', encoding="utf-8")
    if template == "cortex-m":
        _write_cortex_m(root, name)
        print(f"Created package `{name}` in {root}\nNext: cd {root}; read README.md (gg build --no-std --target cortex-m4 --linker-script link.ld)")
        return 0
    (root / "src" / "main.gg").write_text(_TEMPLATES[template].replace("@NAME@", name), encoding="utf-8")
    print(f"Created package `{name}` in {root}\nNext: cd {root}; gg run   (also: gg test, gg fmt, gg doctor)")
    return 0


# -- gg fmt ---------------------------------------------------------------------------------------

def format_source(text: str) -> str:
    from .fmt import format_source as _format
    return _format(text)


def collect_gg_files(paths: list[str]) -> list[Path]:
    files: list[Path] = []
    for p in paths or ["."]:
        pp = Path(p)
        if pp.is_dir():
            files += sorted(x for x in pp.rglob("*.gg") if ".gg-cache" not in x.parts)
        elif pp.is_file():
            files.append(pp)
    return files


def cmd_fmt(paths: list[str], check: bool = False) -> int:
    changed: list[Path] = []
    for f in collect_gg_files(paths):
        old = f.read_text(encoding="utf-8-sig")
        new = format_source(old)
        if new != old:
            changed.append(f)
            if not check:
                f.write_text(new, encoding="utf-8", newline="\n")
    verb = "would reformat" if check else "reformatted"
    for f in changed:
        print(f"{verb}: {f}")
    if not changed:
        print("All files already formatted.")
    return 1 if (check and changed) else 0


# -- gg test --------------------------------------------------------------------------------------

_TEST_RE = re.compile(r"^fn (test_\w+)\(\)\s*:", re.M)
_MAIN_RE = re.compile(r"^fn main\(", re.M)


def discover_tests(source: str) -> list[str]:
    return _TEST_RE.findall(source)


_UNIT_NAME = re.compile(r"test_\w+\Z")


@dataclass
class TestCase:
    name: str
    callable: str
    line: int
    kind: str  # "function" | "block"


def collect_cases(source: str) -> list[TestCase]:
    """`fn test_*():` functions and `test` blocks, in source order."""
    from .ast_nodes import FuncDecl
    from .diagnostics import DiagnosticBag
    from .lexer import tokenize
    from .parser import parse

    diags = DiagnosticBag()
    program = parse(tokenize(source, diags), diags)
    cases: list[TestCase] = []
    seen: set[str] = set()
    for decl in program.decls:
        if not isinstance(decl, FuncDecl) or decl.owner is not None:
            continue
        if decl.is_test:
            cases.append(TestCase(decl.test_label, decl.name, decl.line, "block"))
            seen.add(decl.name)
        elif not decl.params and decl.ret is None and _UNIT_NAME.fullmatch(decl.name):
            cases.append(TestCase(decl.name, decl.name, decl.line, "function"))
            seen.add(decl.name)
    for name in discover_tests(source):
        if name not in seen:
            cases.append(TestCase(name, name, 1, "function"))
    return cases


def _test_document(results: list[dict]) -> dict:
    from . import __version__
    passed = sum(1 for r in results if r["status"] == "passed")
    failed = len(results) - passed
    return {
        "schema_version": 1,
        "tool": {"name": "gg", "version": __version__},
        "command": "test",
        "ok": failed == 0,
        "summary": {"passed": passed, "failed": failed},
        "tests": results,
    }


def cmd_test(paths: list[str], release: bool = False, as_json: bool = False, coverage: bool = False) -> int:
    files = collect_gg_files(paths)
    cov_out = None
    if coverage:
        import os
        cov_out = os.path.abspath(os.environ.get('GG_COV_OUT', '.gg-coverage'))
        Path(cov_out).unlink(missing_ok=True)
    results: list[dict] = []
    for f in files:
        source = f.read_text(encoding="utf-8-sig")
        cases = collect_cases(source)
        if not cases:
            continue
        base = _MAIN_RE.sub("fn __gg_user_main(", source)
        for case in cases:
            tmp = f.with_name(f".gg_test_{f.stem}_{case.callable}.gg")
            tmp.write_text(base + f"\n\nfn main():\n    {case.callable}()\n", encoding="utf-8")
            try:
                cmd = [sys.executable, "-m", "greengold", "run", str(tmp)]
                if release:
                    cmd.append("--release")
                env = None
                if coverage:
                    import os
                    env = dict(os.environ, GG_COVERAGE="1", GG_COV_OUT=cov_out, GG_COV_REMAP=f"{tmp.resolve()}|{f.resolve()}")
                r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", timeout=300, env=env)
            finally:
                tmp.unlink(missing_ok=True)
            message = "" if r.returncode == 0 else ((r.stderr or r.stdout).strip() or "failed")
            results.append({
                "name": case.name,
                "file": f.as_posix(),
                "line": case.line,
                "kind": case.kind,
                "status": "passed" if r.returncode == 0 else "failed",
                "message": message,
            })
            if as_json:
                continue
            if r.returncode == 0:
                print(f"test {f.name}::{case.name} ... ok")
            else:
                print(f"test {f.name}::{case.name} ... FAILED")
                if message:
                    print("    " + message.replace("\n", "\n    "))
    failed = sum(1 for r in results if r["status"] == "failed")
    passed = len(results) - failed
    if as_json:
        json.dump(_test_document(results), sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        print(f"\ntest result: {'ok' if not failed else 'FAILED'}. {passed} passed; {failed} failed")
    if coverage and cov_out and Path(cov_out).is_file() and not as_json:
        from .coverage import run_report
        print()
        run_report(cov_out, False, None)
    return 1 if failed else 0


# -- gg doc ---------------------------------------------------------------------------------------

_DECL_RE = re.compile(r"^(fn|struct|enum|feature|type|const|extern)\b(.*)$")


def generate_docs(text: str, title: str) -> str:
    """Markdown from `#` comment blocks that directly precede a declaration."""
    lines = text.replace("\r\n", "\n").split("\n")
    out = [f"# {title}", ""]
    doc: list[str] = []
    for line in lines:
        s = line.strip()
        if line.startswith("#") and not line.startswith("#!"):
            doc.append(s.lstrip("#").strip())
            continue
        if s in ("public", "private"):
            continue
        m = _DECL_RE.match(line)
        if m:
            sig = line.rstrip().rstrip(":")
            out.append(f"### `{sig}`")
            out.append("")
            if doc:
                out += doc + [""]
        doc = []
    return "\n".join(out).rstrip() + "\n"


def cmd_doc(paths: list[str], output: str | None = None) -> int:
    files = collect_gg_files(paths)
    if not files:
        print("No .gg files found.", file=sys.stderr)
        return 1
    parts = [generate_docs(f.read_text(encoding="utf-8-sig"), f.name) for f in files]
    text = "\n".join(parts)
    if not output:
        if len(paths) == 1 and Path(paths[0]).is_file() and str(paths[0]).endswith(".gg"):
            output = str(Path(paths[0]).with_suffix(".md"))
        else:
            mp = find_manifest()
            if mp is not None:
                output = str(mp.parent / "DOCS.md")
            elif paths and Path(paths[0]).is_dir():
                output = str(Path(paths[0]) / "DOCS.md")
            else:
                output = "DOCS.md"
    if output == "-":
        sys.stdout.write(text)
    else:
        Path(output).write_text(text, encoding="utf-8")
        print(f"Docs written to: {output}")
    return 0


# -- incremental build cache ----------------------------------------------------------------------

def cache_key(program_dump: str, flags: list[str]) -> str:
    h = hashlib.sha256()
    pkg = Path(__file__).parent
    for f in sorted(pkg.rglob("*")):  # every compiler source, prelude and std file
        if f.suffix in (".py", ".gg") and "__pycache__" not in f.parts:
            h.update(f.relative_to(pkg).as_posix().encode("utf-8"))
            h.update(f.read_bytes())
    from .llvm_driver import describe_backend  # a different LLVM makes different code from the same sources
    h.update(describe_backend().encode("utf-8"))
    h.update(program_dump.encode("utf-8"))
    h.update("\0".join(flags).encode("utf-8"))
    return h.hexdigest()[:32]
