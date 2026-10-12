"""Command-line interface: `python -m greengold <command> file.gg` or `gg <command> file.gg`.

Commands: build, run, check, emit-ll, emit-bc, test, fmt, doc, new, explain, api, tokens, ast
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

from .ast_nodes import ImportDecl, Node, Program, dump_ast
from .api import library, library_json, library_text
from .codes import explain_json, explain_text
from .diagnostics import CompileError, Diagnostic, DiagnosticBag, apply_edits, export_json, prepare, render_all, use_color
from .lexer import tokenize
from .parser import parse
from .typecheck import check_program


def _raise_if_errors(diags: DiagnosticBag) -> None:
    if diags.has_errors():
        raise CompileError(diags.items)


# Set from `--color` before a command runs. Library callers leave this false.
_COLOR = False


def _set_color(mode: str) -> None:
    global _COLOR
    _COLOR = use_color(mode, sys.stderr)


def _print_diagnostics(diags: list[Diagnostic], source: str, filename: str,
                       sources: dict[str, str] | None = None) -> None:
    print(render_all(diags, source, filename, sources=sources, color=_COLOR), file=sys.stderr)


STD_DIR = Path(__file__).parent / "std"
DEP_ROOTS: dict[str, Path] = {}  # gg.toml dependencies: name -> import root directory
DEBUG_INFO = False  # `-g`: emit DWARF debug information
NATIVE = None  # native.Native of the active package (C/C++ sources to compile and link)


def _resolve_import_target(base_dir: Path, raw_path: str) -> Path:
    norm = raw_path.replace("\\", "/")
    if norm.startswith("std/"):  # standard library module shipped with the compiler
        std = STD_DIR / norm[4:]
        if std.exists():
            return std
    first, _, rest = norm.partition("/")
    if rest and first in DEP_ROOTS:  # `import mylib.util` with `mylib` declared in gg.toml
        base_dir, raw_path = DEP_ROOTS[first], rest
    p = Path(raw_path)
    if not p.is_absolute():
        p = base_dir / p
    if not p.exists() and not str(p).endswith(".gg"):
        p_gg = p.with_suffix(".gg")
        if p_gg.exists():
            return p_gg
    return p


def _default_bind(raw_path: str) -> str:
    norm = raw_path.replace("\\", "/")
    if norm.endswith(".gg"):
        norm = norm[:-3]
    return norm.split("/")[-1] or norm


def _alloc_slug(canon: Path, owners: dict[str, Path]) -> str:
    """File stem, or `parent_stem` when two imported files share a stem."""
    stem = canon.stem
    if stem not in owners or owners[stem] == canon:
        owners[stem] = canon
        return stem
    parent = canon.parent.name or "mod"
    cand = f"{parent}_{stem}"
    n = 2
    while cand in owners and owners[cand] != canon:
        cand = f"{parent}_{stem}_{n}"
        n += 1
    owners[cand] = canon
    return cand


class _ModuleLoader:
    """Loads each file once. The entry file is the root (bare names). Imports are per file."""

    def __init__(self, diags: DiagnosticBag, overrides: dict[str, str] | None = None) -> None:
        self.diags = diags
        # Path (as given or resolved) -> text to use instead of the file on disk. Used to re-check an edit.
        self.overrides = overrides or {}
        self.skips: dict[str, list[dict]] = {}
        self.slugs: dict[Path, str] = {}
        self.owners: dict[str, Path] = {}
        self.sources: dict[str, str] = {}
        self.decls: list[Node] = []
        self.imports: dict[str, list[tuple[str, str, list[str], ImportDecl]]] = {}

    def load_path(self, file_path: Path, imp_decl: ImportDecl | None, as_root: bool) -> str | None:
        try:
            canon = file_path.resolve()
        except OSError:
            canon = file_path
        if canon in self.slugs:
            return self.slugs[canon]
        content = self.overrides.get(str(file_path), self.overrides.get(str(canon)))
        if content is None and not file_path.exists():
            self._missing(imp_decl, file_path, f"Imported file not found: `{file_path}`.",
                          "Check file name and path.")
            return None
        if content is None:
            try:
                content = file_path.read_text(encoding="utf-8-sig")
            except OSError as exc:
                self._missing(imp_decl, file_path, f"Failed to read `{file_path}`: {exc.strerror}", None)
                return None
        f_str = str(file_path)
        self.sources[f_str] = content
        self.sources[str(canon)] = content
        slug = "" if as_root else _alloc_slug(canon, self.owners)
        self.slugs[canon] = slug
        if not self._parse_into(content, f_str, file_path.parent, slug):
            return slug
        return slug

    def load_text(self, source: str, filename: str) -> None:
        """Entry source is the program root."""
        self.sources[filename] = source
        if filename != "<source>":
            try:
                canon = Path(filename).resolve()
            except OSError:
                canon = Path(filename)
            self.slugs[canon] = ""
            self.sources[str(canon)] = source
        base = Path(filename).parent if filename != "<source>" else Path.cwd()
        self._parse_into(source, filename, base, "")

    def _parse_into(self, content: str, filename: str, base_dir: Path, slug: str) -> bool:
        # A syntax error does not stop the file: the parser skips the broken line, and the type checker
        # still reports the other mistakes (see `analyze`).
        file_diags = DiagnosticBag()
        tokens = tokenize(content, file_diags)
        sub_prog = parse(tokens, file_diags, filename=filename)
        self.skips[filename] = list(getattr(sub_prog, "syntax_skips", []))
        if file_diags.has_errors():
            self._take_diags(file_diags, filename)
        binds: list[tuple[str, str, list[str], ImportDecl]] = []
        seen: dict[str, ImportDecl] = {}
        for decl in sub_prog.decls:
            if isinstance(decl, ImportDecl):
                target = _resolve_import_target(base_dir, decl.path)
                tslug = self.load_path(target, decl, as_root=False)
                if tslug is None:
                    continue
                if tslug == slug:
                    self.diags.error("A file cannot import itself.", decl.line, decl.col, decl.length,
                                     "Remove this import.", filename=filename)
                    continue
                if decl.names:
                    for item in decl.names:
                        self._bind(seen, binds, item, tslug, [item], decl, filename)
                else:
                    local = decl.alias or _default_bind(decl.path)
                    self._bind(seen, binds, local, tslug, [], decl, filename)
            else:
                decl.module_slug = slug  # type: ignore[attr-defined]
                self.decls.append(decl)
        self.imports[slug] = binds
        return True

    def _bind(self, seen: dict[str, ImportDecl], binds: list, local: str, target: str,
              names: list[str], decl: ImportDecl, filename: str) -> None:
        prev = seen.get(local)
        if prev is not None:
            self.diags.error(f"Import name `{local}` is already used in this file.",
                             decl.line, decl.col, decl.length,
                             "Rename one import with `as`.", filename=filename)
            return
        seen[local] = decl
        binds.append((local, target, names, decl))

    def _take_diags(self, file_diags: DiagnosticBag, filename: str) -> None:
        for d in file_diags.items:
            if not d.filename:
                d.filename = filename
            self.diags.items.append(d)

    def _missing(self, imp_decl: ImportDecl | None, file_path: Path, message: str, hint: str | None) -> None:
        line = imp_decl.line if imp_decl else 1
        col = imp_decl.col if imp_decl else 1
        length = imp_decl.length if imp_decl else 1
        fname = getattr(imp_decl, "filename", None) or str(file_path)
        self.diags.error(message, line, col, length, hint=hint, filename=fname)

    def program(self) -> Program:
        prog = Program(self.decls, line=1, col=1, imports=self.imports)
        prog.syntax_skips = self.skips  # type: ignore[attr-defined]
        return prog


def load_sources_and_ast(
    files: list[str | Path],
    initial_source: str | None = None,
    initial_filename: str = "<source>",
    diags: DiagnosticBag | None = None,
    overrides: dict[str, str] | None = None,
) -> tuple[Program, dict[str, str], DiagnosticBag]:
    """Loads the entry file and each import once. Each file is its own module."""
    if diags is None:
        diags = DiagnosticBag()
    loader = _ModuleLoader(diags, overrides)
    if initial_source is not None:
        loader.load_text(initial_source, initial_filename)
    for i, f in enumerate(files):
        loader.load_path(Path(f), None, as_root=initial_source is None and i == 0)
    return loader.program(), loader.sources, diags


def analyze(files: list[str | Path], initial_source: str | None = None, initial_filename: str = "<source>",
            overrides: dict[str, str] | None = None, require_main: bool = True):
    """Front end for tools: load, parse, and type-check, even past syntax errors.

    With a syntax error the broken line is skipped and the rest is still checked, so one run shows every
    mistake. Diagnostics that only exist because of the skipped text are hidden as cascades.
    Returns (program, sources, diags, checker); checker is None when type checking could not run.
    """
    diags = DiagnosticBag()
    program, sources, diags = load_sources_and_ast(files, initial_source, initial_filename, diags, overrides)
    primary = str(files[0]) if files else initial_filename
    syntax = [d for d in diags.items if d.severity == "error"]
    before = len(diags.items)
    checker = None
    try:
        checker = check_program(program, diags, primary, require_main=require_main)
    except Exception:  # a half-parsed file can confuse later passes; the syntax errors still stand
        if not syntax:
            raise
    if syntax:
        _hide_recovery_cascades(diags.items[before:], syntax, getattr(program, "syntax_skips", {}))
    return program, sources, diags, checker


def _hide_recovery_cascades(found: list[Diagnostic], syntax: list[Diagnostic], skips: dict[str, list[dict]]) -> None:
    """Hide type errors that come from text the parser had to skip."""
    import re
    roots: dict[str | None, Diagnostic] = {}
    for d in syntax:
        roots.setdefault(d.filename, d)
    fallback = syntax[0]
    for d in found:
        file_skips = skips.get(d.filename or "", []) if d.filename else [s for v in skips.values() for s in v]
        names: set[str] = set()
        for sk in file_skips:
            names |= sk["names"]
        mentioned = set(re.findall(r"`([A-Za-z_][A-Za-z0-9_.]*)", d.message))
        mentioned |= {m.split(".")[-1] for m in mentioned}
        on_skipped_line = any(sk["first"] <= d.line <= sk["last"] for sk in file_skips)
        cascade = (
            on_skipped_line
            or bool(mentioned & names)
            or d.rule in ("missing-main", "missing-return")
            or (any(sk["top"] for sk in file_skips) and d.rule in ("undefined-name", "unknown-type", "unknown-method",
                                                                    "unknown-field", "wrong-arity"))
        )
        if cascade:
            d.hidden = True
            d.cascade = True
            d.cause = roots.get(d.filename, fallback)


def lex_source(source: str):
    diags = DiagnosticBag()
    tokens = tokenize(source, diags)
    _raise_if_errors(diags)
    return tokens


def parse_source(source: str):
    """Generates AST from source (no type checking)."""
    diags = DiagnosticBag()
    tokens = tokenize(source, diags)
    _raise_if_errors(diags)
    program = parse(tokens, diags)
    _raise_if_errors(diags)
    return program


def compile_to_ir(source: str, filename: str = "<source>", release: bool = False, unchecked: bool = False,
                  target: str | None = None) -> str:
    """Full pipeline: lexer -> parser -> import resolution -> type/move analysis -> LLVM IR text.
    CompileError on failure."""
    program, sources, diags = load_sources_and_ast([], initial_source=source, initial_filename=filename)
    _raise_if_errors(diags)
    check_program(program, diags, filename)
    _raise_if_errors(diags)
    return _gen_llvm(program, filename, release, unchecked, target)


def build_source(source: str, exe_path: Path, filename: str = "<source>", release: bool = False,
                 unchecked: bool = False, links: list[str] | None = None) -> int:
    """Compiles source text to an executable. CompileError on a front-end error; 0 on success."""
    program, sources, diags = load_sources_and_ast([], initial_source=source, initial_filename=filename)
    _raise_if_errors(diags)
    check_program(program, diags, filename)
    _raise_if_errors(diags)
    return _build_llvm(program, filename, Path(exe_path), release, links, unchecked)


def _read_source(path: str) -> str | None:
    try:
        return Path(path).read_text(encoding="utf-8-sig")
    except OSError as exc:
        print(f"Error: failed to read `{path}`: {exc.strerror}", file=sys.stderr)
        return None


def _exe_suffix() -> str:
    return ".exe" if os.name == "nt" else ""


def _frontend(files: list[str] | str) -> tuple[Program, str] | None:
    """Lexer -> parser -> import -> type/move/borrow checks. Prints errors and returns None on failure."""
    file_list = [files] if isinstance(files, (str, Path)) else [str(f) for f in files]
    program, sources, diags, _checker = analyze(file_list)
    primary_file = file_list[0]
    if diags.has_errors():
        _print_diagnostics(diags.items, sources.get(primary_file, ""), primary_file, sources)
        return None
    return program, primary_file


def _recheck(text: str, filename: str, primary: str | None = None, require_main: bool = True) -> list[Diagnostic]:
    """Front end with one file replaced by `text`. Used to see whether a suggested fix removes the diagnostic."""
    root = primary or filename
    try:
        _program, _sources, diags, _checker = analyze([root], overrides={filename: text, str(Path(filename).resolve()): text},
                                                      require_main=require_main)
    except Exception:
        return [Diagnostic("recheck failed", 1, 1, code="GG0404")]
    prepare(diags.items)
    return [d for d in diags.items if not d.hidden and not d.cascade]


def verify_fixes(items: list[Diagnostic], sources: dict[str, str], primary: str, limit: int = 40,
                 require_main: bool = True, targets: list[Diagnostic] | None = None) -> None:
    """Set `fix.verified` only when applying the edits removes that diagnostic and adds no new one."""
    visible = [d for d in items if not d.hidden]
    before = Counter((d.code, d.message) for d in visible)
    # A fix may uncover diagnostics that were hidden as cascades of it; those are not new.
    known = Counter((d.code, d.message) for d in items if not d.hidden or d.category != "syntax")
    checked = 0
    for diag in (visible if targets is None else [d for d in targets if not d.hidden]):
        for fix in diag.fixes:
            if checked >= limit or fix.applicability == "manual" or not fix.edits:
                fix.verified = False
                continue
            file = fix.edits[0].filename or diag.filename or primary
            if any((edit.filename or file) != file for edit in fix.edits):
                fix.verified = False
                continue
            src = sources.get(file)
            if src is None:
                fix.verified = False
                continue
            try:
                updated = apply_edits(src, fix.edits)
            except ValueError:
                fix.verified = False
                continue
            after = Counter((d.code, d.message) for d in _recheck(updated, file, primary, require_main))
            key = (diag.code, diag.message)
            checked += 1
            if after[key] >= before[key]:
                fix.verified = False
                continue
            base = known.copy()
            base[key] = before[key] - 1
            fix.verified = all(count <= base[name] for name, count in after.items())
    for diag in visible:
        guesses = [f for f in diag.fixes if f.alternative]
        good = [f for f in guesses if f.verified]
        if len(guesses) > 1 and len(good) == 1:
            good[0].applicability = "safe"  # the only repair that works


def cmd_api(as_json: bool, lock: bool = False, check: bool = False) -> int:
    if lock or check:
        return cmd_api_lock(as_json, write=lock)
    doc = library()
    sys.stdout.write(library_json(doc) if as_json else library_text(doc))
    return 0


def _warn_api_lock(manifest) -> None:
    """`gg build` of a package with gg.api.lock: warn about breaking changes the version does not allow."""
    from . import apilock
    try:
        found = apilock.check_lock(manifest.root, manifest.version)
    except (ValueError, OSError):
        return  # the build itself reports compile errors
    if not found:
        return
    changes, locked = found
    if apilock.allows_breaking(locked, manifest.version):
        return
    for c in changes:
        if c.breaking:
            print(f"warning: public API: {c.message} (locked at {locked}; see `gg api --check`)", file=sys.stderr)


def cmd_api_lock(as_json: bool, write: bool) -> int:
    """`gg api --lock` writes gg.api.lock; `gg api --check` compares the package against it."""
    from . import apilock, tools
    mp = tools.find_manifest()
    if mp is None:
        print("Error: no gg.toml found; `gg api --lock` and `--check` work on a package.", file=sys.stderr)
        return 1
    manifest = tools.load_manifest(mp)
    tools.activate_manifest(manifest)
    try:
        if write:
            path = apilock.write_lock(manifest.root, manifest.name, manifest.version)
            print(f"Wrote {path.name} for {manifest.name} {manifest.version}.")
            return 0
        found = apilock.check_lock(manifest.root, manifest.version)
    except ValueError as err:
        print(f"Error: {err}", file=sys.stderr)
        return 1
    if found is None:
        print(f"Error: no {apilock.LOCK}; write one with `gg api --lock`.", file=sys.stderr)
        return 1
    changes, locked = found
    allowed = apilock.allows_breaking(locked, manifest.version)
    blocking = [c for c in changes if c.breaking and not allowed]
    if as_json:
        json.dump({"locked_version": locked, "version": manifest.version, "breaking_allowed": allowed,
                   "changes": [{"symbol": c.key, "breaking": c.breaking, "message": c.message} for c in changes]},
                  sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 1 if blocking else 0
    for c in changes:
        word = "breaking" if c.breaking else "compatible"
        print(f"{'error' if c.breaking and not allowed else 'note'}: {word}: {c.message}")
    if blocking:
        nxt = apilock._version(locked)
        need = f"{nxt[0] + 1}.0.0" if nxt[0] > 0 else f"0.{nxt[1] + 1}.0"
        print(f"\n{len(blocking)} breaking change(s) since {locked}. Raise the version in gg.toml to {need} "
              f"(or undo the change), then run `gg api --lock`.")
        return 1
    if not changes:
        print(f"The public API matches {apilock.LOCK} ({locked}).")
    return 0


def debug_scripts() -> dict[str, Path]:
    """The debugger printers that ship with the compiler."""
    here = Path(__file__).resolve().parent / "debug"
    names = {"gdb": "gdb_printers.py", "lldb": "lldb_formatters.py"}
    if getattr(sys, "frozen", False):  # a single-file build unpacks into a folder that goes away on exit
        keep = Path.home() / ".greengold" / "debug"
        keep.mkdir(parents=True, exist_ok=True)
        for name in names.values():
            data = (here / name).read_bytes()
            if not (keep / name).is_file() or (keep / name).read_bytes() != data:
                (keep / name).write_bytes(data)
        here = keep
    return {tool: here / name for tool, name in names.items()}


def cmd_debug_scripts() -> int:
    """`gg debug-scripts`: where the gdb and lldb printers are and how to load them."""
    paths = debug_scripts()
    gdb, lldb = paths["gdb"].as_posix(), paths["lldb"].as_posix()
    print("Printers that show `string`, `List`, `HashMap`, and enums as values in a `gg build -g` program.")
    print(f"gdb  (in gdb, or in ~/.gdbinit):   source {gdb}")
    print(f"lldb (in lldb, or in ~/.lldbinit): command script import {lldb}")
    return 0


def cmd_toolchain() -> int:
    """`gg toolchain`: what this compiler runs on and which tools it found (linker, zig, debuggers)."""
    import platform
    from . import llvm_tools, targets
    from .codegen_llvm import init_llvm, native_triple
    from .llvm_driver import backend, describe_backend, find_linker, has_llvmlite
    init_llvm()
    from . import __version__ as version
    host = native_triple(None)
    frozen = " (single-file build)" if getattr(sys, "frozen", False) else ""
    print(f"greengold   {version}{frozen}")
    print(f"python      {platform.python_version()}  {sys.executable}")
    print(f"backend     {describe_backend()}  (GG_BACKEND=llvmlite|clang chooses)")
    if backend() != "llvmlite":
        print(f"llvmlite    {'installed' if has_llvmlite() else 'not installed'}")
    else:
        print(f"clang       {llvm_tools.describe()}  (GG_LLVM picks another, `zig` for the one in Zig)")
    from .llvm_driver import PREFERRED_LLVM, llvmlite_major
    if has_llvmlite() and backend() == "llvmlite" and llvmlite_major() < PREFERRED_LLVM:
        print(f"note        LLVM {llvmlite_major()} is older than LLVM {PREFERRED_LLVM}; "
              "pip install -U \"llvmlite>=0.50\" for faster code")
    print(f"host        {host}")
    linker = find_linker(host)
    print(f"linker      {' '.join(linker) if linker else 'none found'}")
    zig = targets.zig_path()
    print(f"zig         {zig or 'not found (pip install ziglang: links for every target with nothing else installed)'}")
    for tool in ("gdb", "lldb"):
        print(f"{tool:11} {shutil.which(tool) or 'not found'}")
    if linker is None:
        print("Nothing can link programs here: install gcc or clang, or run `pip install ziglang`.")
        return 1
    return 0


def cmd_targets() -> int:
    """`gg targets`: the target names `--target` accepts, and whether this machine can link for them."""
    from . import targets
    from . import llvm_tools
    from .codegen_llvm import init_llvm, native_triple
    from .llvm_driver import backend
    init_llvm()
    host = native_triple(None)
    print(f"host: {host}")
    for name, triple in targets.ALIASES.items():
        if backend() == "llvmlite":
            import llvmlite.binding as llvm
            try:
                llvm.Target.from_triple(triple)
                code = "yes"
            except RuntimeError:
                code = "no"
        else:
            code = "yes" if llvm_tools.has_target(triple) else "no"
        if not targets.is_cross(triple):
            link = "host toolchain"
        else:
            hosted = targets.cross_linker(triple, False)
            free = targets.cross_linker(triple, True)
            link = "yes" if hosted else ("--no-std only" if free else "no (object file)")
        print(f"  {name:14} {triple:28} code: {code:4} link: {link}")
    print("Any LLVM triple works with --target; these are short names.")
    return 0


def cmd_packages(command: str, index: str | None = None) -> int:
    """`gg fetch` (resolve and download, keep gg.lock), `gg update` (re-resolve), `gg publish`."""
    from . import packages, tools
    mp = tools.find_manifest()
    if mp is None:
        print(f"Error: no gg.toml found; `gg {command}` works on a package.", file=sys.stderr)
        return 1
    try:
        if command == "publish":
            target = index or os.environ.get("GG_REGISTRY")
            if not target:
                print("Error: give the registry index directory: `gg publish --index DIR` or GG_REGISTRY.",
                      file=sys.stderr)
                return 1
            print("Published", packages.publish(mp.parent, target))
            return 0
        found = packages.resolve(mp.parent, update=command == "update")
    except packages.PackageError as err:
        print(f"Error: {err}", file=sys.stderr)
        return 1
    for name, where in sorted(found.items()):
        print(f"{name}: {where}")
    print(f"{len(found)} dependenc{'y' if len(found) == 1 else 'ies'}; pinned in {packages.LOCK}.")
    return 0


def cmd_explain(code: str, as_json: bool) -> int:
    code = code.upper()
    if as_json:
        body = explain_json(code)
        if body is None:
            print(f"Error: unknown error code `{code}`.", file=sys.stderr)
            return 1
        json.dump(body, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0
    text = explain_text(code)
    if text is None:
        print(f"Error: unknown error code `{code}`.", file=sys.stderr)
        return 1
    sys.stdout.write(text)
    return 0


def cmd_check(files: list[str], as_json: bool) -> int:
    _program, sources, diags, _checker = analyze(files)
    primary = files[0]
    prepare(diags.items)
    verify_fixes(diags.items, sources, primary)
    from .diagnostics import reset_prepared
    reset_prepared(diags.items)
    if as_json:
        doc = export_json(diags.items, sources, primary, "check", sources.get(primary, ""))
        json.dump(doc, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0 if doc["ok"] else 1
    src = sources.get(primary, "")
    if any(d.severity == "error" and not d.hidden for d in diags.items):
        _print_diagnostics(diags.items, src, primary, sources)
        shown = [d for d in diags.items if not d.hidden]
        safe = sum(1 for d in shown if any(f.verified and f.applicability == "safe" for f in d.fixes))
        likely = sum(1 for d in shown if any(f.verified and f.applicability == "likely" for f in d.fixes)
                     and not any(f.verified and f.applicability == "safe" for f in d.fixes))
        if safe:
            print(f"`gg fix {primary}` repairs {safe} of them.", file=sys.stderr)
        if likely:
            print(f"`gg fix --likely {primary}` also applies {likely} suggested fix(es).", file=sys.stderr)
        return 1
    print("ok")
    return 0


def _choose_fixes(visible: list[Diagnostic], file: str, likely: bool) -> list:
    """One verified fix per diagnostic, with edits only in `file`."""
    chosen = []
    for diag in visible:
        for fix in diag.fixes:
            if not fix.verified or not fix.edits:
                continue
            if fix.applicability != "safe" and not (likely and fix.applicability == "likely"):
                continue
            if any(e.filename and not _same_path(e.filename, file) for e in fix.edits):
                continue
            if diag.filename and not _same_path(diag.filename, file) and not all(e.filename for e in fix.edits):
                continue
            chosen.append((diag, fix))
            break
    return chosen


def _same_path(a: str, b: str) -> bool:
    try:
        return Path(a).resolve() == Path(b).resolve()
    except OSError:
        return a == b


def fix_source(text: str, file: str, likely: bool = False, rounds: int = 25) -> tuple[str, list[tuple[int, str]], list[Diagnostic]]:
    """Apply verified fixes to `text` until none is left. Returns (new text, [(line, description)], remaining)."""
    from .diagnostics import char_offset
    require_main = bool(re.search(r"^fn main\(", text, re.M))
    applied: list[tuple[int, str]] = []
    remaining: list[Diagnostic] = []
    for _ in range(rounds):
        _program, sources, diags, _checker = analyze([file], overrides={file: text, str(Path(file).resolve()): text},
                                                     require_main=require_main)
        visible = prepare(diags.items)
        remaining = visible
        srcs = dict(sources)
        srcs[file] = text
        verify_fixes(diags.items, srcs, file, limit=200, require_main=require_main)
        chosen = _choose_fixes(visible, file, likely)
        if not chosen:
            break
        # Apply every non-overlapping fix of this round at once; the next round re-checks the result.
        spans: list[tuple[int, int]] = []
        edits = []
        picked = []
        for diag, fix in chosen:
            mine = [(char_offset(text, e.start_line, e.start_col), char_offset(text, e.end_line, e.end_col)) for e in fix.edits]
            if any(not (b <= s0 or a >= s1) or (a == b == s0 == s1) for a, b in mine for s0, s1 in spans):
                continue
            spans += mine
            edits += fix.edits
            picked.append((diag, fix))
        try:
            new_text = apply_edits(text, edits)
        except ValueError:
            diag, fix = picked[0]
            new_text = apply_edits(text, fix.edits)
            picked = picked[:1]
        if new_text == text:
            break
        text = new_text
        applied += [(diag.line, fix.description) for diag, fix in picked]
    return text, applied, remaining


def cmd_fix(paths: list[str], dry_run: bool = False, likely: bool = False) -> int:
    from .tools import collect_gg_files
    total = 0
    left = 0
    for f in collect_gg_files(paths):
        old = f.read_text(encoding="utf-8-sig")
        new, applied, remaining = fix_source(old, str(f), likely)
        for line, description in applied:
            print(f"{f}:{line}: {description}")
        total += len(applied)
        left += sum(1 for d in remaining if d.severity == "error")
        if new != old and not dry_run:
            f.write_text(new, encoding="utf-8", newline="\n")
    verb = "would apply" if dry_run else "applied"
    print(f"{verb} {total} fix(es); {left} error(s) need a decision (`gg check` shows them).")
    if not likely:
        print("`gg fix --likely` also applies fixes that are probably, but not certainly, what you meant.")
    return 0 if left == 0 else 1


def _is_freestanding(target: str | None, no_std: bool) -> bool:
    from .targets import is_wasm, triple_of
    return no_std or target == "bare-metal" or (target is not None and is_wasm(triple_of(target)))


def _gen_llvm(program: Program, primary_file: str, release: bool, unchecked: bool, target: str | None = None,
              no_std: bool = False) -> str:
    from .codegen_llvm import generate_llvm
    return generate_llvm(program, filename=primary_file, release=release, unchecked=unchecked, target=target,
                         leakcheck=bool(os.environ.get("GG_LEAKCHECK")),
                         freestanding=_is_freestanding(target, no_std), debug=DEBUG_INFO)


def _can_link_freestanding(triple: str, target: str | None) -> bool:
    """Libc-free `_start` can only be directly executed on Linux x86_64 host."""
    return target != "bare-metal" and "linux" in triple and triple.startswith("x86_64")


def _build_llvm(program: Program, primary_file: str, exe_path: Path, release: bool, links: list[str] | None,
                unchecked: bool, target: str | None = None, no_std: bool = False) -> int:
    from .codegen_llvm import CodegenError, native_triple
    from .llvm_driver import LLVMError, link_executable, object_code
    triple = native_triple(target)
    free = _is_freestanding(target, no_std)
    try:
        ir_text = _gen_llvm(program, primary_file, release, unchecked, target, no_std)
        obj = object_code(ir_text, triple, release)
    except (LLVMError, CodegenError) as err:
        print(f"Error: {err}", file=sys.stderr)
        return 1
    from . import targets
    if NATIVE is not None and NATIVE.sources and not free:  # the package's C/C++ sources
        from .native import NativeError, build as build_native
        if target is not None and targets.is_cross(triple):
            print("Error: native C/C++ sources are built only for the host; cross builds of them are not supported yet.",
                  file=sys.stderr)
            return 1
        try:
            links = build_native(NATIVE, Path(".gg-cache") / "native") + list(links or [])
        except NativeError as err:
            print(f"Error: {err}", file=sys.stderr)
            return 1
    elif NATIVE is not None and NATIVE.libs:
        links = [f"-l{lib}" for lib in NATIVE.libs] + list(links or [])
    if target is not None and target != "bare-metal" and targets.is_cross(triple):
        return _link_cross(obj, exe_path, triple, links, free)
    if free and not _can_link_freestanding(triple, target):  # output: object file only
        obj_out = exe_path.with_suffix(".o")
        obj_out.write_bytes(obj)
        print(f"Object file written: {obj_out}  (target: {triple}; linking is up to you)")
        return 3
    with tempfile.TemporaryDirectory(prefix="greengold_") as tmp:
        obj_path = Path(tmp) / "program.o"
        obj_path.write_bytes(obj)
        return link_executable(obj_path, exe_path, triple, links, freestanding=free)


def _link_cross(obj: bytes, exe_path: Path, triple: str, links: list[str] | None, free: bool) -> int:
    """Links for another machine with a toolchain for it, or writes the object file and says how."""
    from . import targets
    from .llvm_driver import link_args
    if targets.is_wasm(triple) and exe_path.suffix != ".wasm":
        exe_path = exe_path.with_suffix(".wasm")
    cmd = targets.cross_linker(triple, free)
    if cmd is None:
        obj_out = exe_path.with_suffix(".o")
        obj_out.write_bytes(obj)
        print(f"Object file written: {obj_out}  (target: {triple})")
        print(f"No linker for {triple} was found. Link it with: {targets.how_to_link(triple, obj_out.name)}")
        return 3
    with tempfile.TemporaryDirectory(prefix="greengold_") as tmp:
        obj_path = Path(tmp) / "program.o"
        obj_path.write_bytes(obj)
        full = targets.link_command(cmd, triple, str(obj_path), str(exe_path), free) + link_args(links)
        res = subprocess.run(full, capture_output=True, text=True)
    if res.returncode != 0:
        print(f"Error: linking for {triple} failed:", file=sys.stderr)
        print(res.stderr or res.stdout, file=sys.stderr)
        return 1
    print(f"Compiled: {exe_path}  (target: {triple})")
    return 3


def cmd_build(files: list[str] | str, output: str | None, release: bool = False, links: list[str] | None = None,
              unchecked: bool = False, target: str | None = None, no_std: bool = False) -> int:
    front = _frontend(files)
    if front is None:
        return 1
    program, primary_file = front
    src = Path(primary_file)
    exe_path = Path(output) if output else src.with_suffix(_exe_suffix())
    from .tools import cache_key
    native_key = ""
    if NATIVE is not None:  # a changed C/C++ source makes a new program
        import hashlib
        h = hashlib.sha256(repr(NATIVE.libs).encode())
        for path, flags in NATIVE.sources:
            h.update(path.read_bytes() + repr(flags).encode())
        native_key = h.hexdigest()
    key = cache_key(dump_ast(program), [str(release), str(unchecked), str(target), str(no_std), str(links),
                                        primary_file, _exe_suffix(), "recur-inline-2", f"g={DEBUG_INFO}", native_key])
    cached = Path(".gg-cache") / f"{key}{_exe_suffix()}"
    if cached.is_file() and target is None and not no_std:
        exe_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(cached, exe_path)
        shutil.copymode(cached, exe_path)
        print(f"Up to date (cached): {exe_path}")
        return 0
    code = _build_llvm(program, primary_file, exe_path, release, links, unchecked, target, no_std)
    if code == 3:  # only object file generated (bare-metal)
        return 0
    if code == 0:
        print(f"Compiled: {exe_path}  (LLVM)")
        if target is None and not no_std and exe_path.is_file():
            cached.parent.mkdir(exist_ok=True)
            shutil.copyfile(exe_path, cached)
            shutil.copymode(exe_path, cached)
    return code


def cmd_run(files: list[str] | str, release: bool = False, links: list[str] | None = None,
            unchecked: bool = False, target: str | None = None, no_std: bool = False) -> int:
    front = _frontend(files)
    if front is None:
        return 1
    program, primary_file = front
    with tempfile.TemporaryDirectory(prefix="greengold_") as tmp:
        exe_path = Path(tmp) / ("program" + _exe_suffix())
        code = _build_llvm(program, primary_file, exe_path, release, links, unchecked, target, no_std)
        if code == 3:
            print("Error: this target cannot be run directly; use `build` to emit object file.", file=sys.stderr)
            return 1
        if code != 0:
            return code
        sys.stdout.flush()
        return subprocess.run([str(exe_path)]).returncode


def cmd_emit_llvm(files: list[str], release: bool, unchecked: bool, bitcode_out: str | None, optimized: bool,
                  target: str | None = None, no_std: bool = False, ir_out: str | None = None) -> int:
    from .codegen_llvm import CodegenError, native_triple
    from .llvm_driver import LLVMError, bitcode, optimized_ir
    front = _frontend(files)
    if front is None:
        return 1
    program, primary_file = front
    triple = native_triple(target)
    try:
        ir_text = _gen_llvm(program, primary_file, release, unchecked, target, no_std)
        if bitcode_out is not None:
            Path(bitcode_out).write_bytes(bitcode(ir_text, triple, release))
            print(f"Bitcode written: {bitcode_out}")
            return 0
        final_ir = optimized_ir(ir_text, triple, release) if optimized else ir_text
        out_target = ir_out or str(Path(primary_file).with_suffix(".ll"))
        if out_target == "-":
            sys.stdout.write(final_ir)
        else:
            Path(out_target).write_text(final_ir, encoding="utf-8")
            if ir_out is not None:
                print(f"LLVM IR written to: {out_target}")
            else:
                sys.stdout.write(final_ir)
    except (LLVMError, CodegenError) as err:
        print(f"Error: {err}", file=sys.stderr)
        return 1
    return 0


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="gg", description="Greengold language compiler: .gg -> LLVM IR -> machine code")
    p.add_argument("--color", choices=("auto", "always", "never"), default="auto",
                   help="color error output: auto (a terminal, unless NO_COLOR is set), always, or never")
    from . import __version__, editions
    p.add_argument("--version", action="version",
                   version=f"gg {__version__} (language editions: {', '.join(editions.EDITIONS)}; "
                           f"latest {editions.LATEST})")
    sub = p.add_subparsers(dest="command", required=True)
    # SUPPRESS so a subcommand that omits --color does not reset a flag placed before the command.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--color", choices=("auto", "always", "never"), default=argparse.SUPPRESS,
                        help="color error output: auto (a terminal, unless NO_COLOR is set), always, or never")

    def add(name: str, **kwargs):
        parents = list(kwargs.pop("parents", []))
        return sub.add_parser(name, parents=[*parents, common], **kwargs)
    b = add("build", help="Emit LLVM IR, compile to machine code, and link")
    b.add_argument("files", nargs="*", help="source file(s) (default: gg.toml main)")
    b.add_argument("-o", "--output", help="output file (default: next to source)")
    b.add_argument("--release", action="store_true", help="optimize (LLVM -O3); bounds checks remain enabled")
    b.add_argument("--unchecked", action="store_true", help="UNSAFE: remove array/slice/string bounds checks")
    b.add_argument("--link", action="append", default=[], help="link C library (passed as -l)")
    b.add_argument("-L", "--link-path", action="append", default=[], help="library search path (passed as -L)")
    b.add_argument("--link-file", action="append", default=[], help="file to link directly (.a, .o, .lib, .so, .dll)")
    b.add_argument("--target", help="target triple or `bare-metal` (default: host machine)")
    b.add_argument("--no-std", action="store_true", help="compile without libc/OS (no print, input, heap; Core is used)")
    b.add_argument("-g", "--debug", action="store_true", help="emit debug information (DWARF) for debuggers")

    r = add("run", help="compile and run")
    r.add_argument("files", nargs="*", help="source file(s) (default: gg.toml main)")
    r.add_argument("--release", action="store_true", help="optimize (LLVM -O3); bounds checks remain enabled")
    r.add_argument("--unchecked", action="store_true", help="UNSAFE: remove array/slice/string bounds checks")
    r.add_argument("--link", action="append", default=[], help="link C library (passed as -l)")
    r.add_argument("-L", "--link-path", action="append", default=[], help="library search path (passed as -L)")
    r.add_argument("--link-file", action="append", default=[], help="file to link directly (.a, .o, .lib, .so, .dll)")
    r.add_argument("--target", help="target triple (default: host machine)")
    r.add_argument("--no-std", action="store_true", help="compile without libc/OS (can only be run on Linux x86_64)")
    r.add_argument("-g", "--debug", action="store_true", help="emit debug information (DWARF) for debuggers")

    ll = add("emit-ll", help="emit LLVM IR (.ll file, default: next to source)")
    ll.add_argument("files", nargs="+", help="source file(s)")
    ll.add_argument("-o", "--output", help="output .ll file (default: next to source)")
    ll.add_argument("--release", action="store_true", help="emit in release mode and print optimized IR")
    ll.add_argument("--unchecked", action="store_true", help="UNSAFE: remove bounds checks")
    ll.add_argument("--target", help="target triple or `bare-metal`")
    ll.add_argument("--no-std", action="store_true", help="compile without libc/OS")
    ll.add_argument("-g", "--debug", action="store_true", help="emit debug information (DWARF)")

    bc = add("emit-bc", help="write LLVM bitcode (.bc) file")
    bc.add_argument("files", nargs="+", help="source file(s)")
    bc.add_argument("-o", "--output", help="output file (default: .bc next to source)")
    bc.add_argument("--release", action="store_true", help="optimize")
    bc.add_argument("--unchecked", action="store_true", help="UNSAFE: remove bounds checks")
    bc.add_argument("--target", help="target triple or `bare-metal`")
    bc.add_argument("--no-std", action="store_true", help="compile without libc/OS")

    bg = add("bindgen", help="generate Greengold `extern` declarations from C header")
    bg.add_argument("header", help="C header file (.h)")
    bg.add_argument("-o", "--output", help="output .gg file (default: next to header)")
    bg.add_argument("--header-name", help="header name to write as `extern \"name.h\" fn ...`")
    bg.add_argument("--cpp", action="store_true",
                    help="C++ header: also write <name>_shim.cpp (extern \"C\" entry points) and wrap classes")

    tok_p = add("tokens", help="print token list (debug)")
    tok_p.add_argument("file")
    tok_p.add_argument("-o", "--output", help="output tokens file (default: stdout)")

    ast_p = add("ast", help="print AST (debug)")
    ast_p.add_argument("files", nargs="+", help="source file(s)")
    ast_p.add_argument("-o", "--output", help="output AST file (default: stdout)")

    lsp_p = add("lsp", help="start LSP (Language Server Protocol) server")
    lsp_p.add_argument("--stdio", action="store_true", help="communicate over stdio (default)")
    add("targets", help="list target names for --target and whether they can be linked here")
    add("toolchain", help="show the LLVM version, the linker, zig, and debuggers this compiler found")
    add("debug-scripts", help="print how to load the gdb/lldb printers for `string`, `List`, `HashMap`, enums")
    add("fetch", help="download the dependencies in gg.toml and pin them in gg.lock")
    add("update", help="resolve the dependencies again (newest allowed versions) and rewrite gg.lock")
    pb = add("publish", help="add this package's version (its current git commit) to a registry index")
    pb.add_argument("--index", help="registry index directory (default: GG_REGISTRY)")
    nw = add("new", help="create a package (gg.toml + src/main.gg)")
    nw.add_argument("name")
    nw.add_argument("--path", help="directory (default: ./<name>)")
    fm = add("fmt", help="rewrite .gg files into the one canonical layout")
    fm.add_argument("paths", nargs="*", help="files or directories (default: .)")
    fm.add_argument("--check", action="store_true", help="only report files that would change (exit 1)")
    ts = add("test", help="run `fn test_*():` functions and `test` blocks (a panic = failure)")
    ts.add_argument("paths", nargs="*", help="files or directories (default: .)")
    ts.add_argument("--release", action="store_true")
    ts.add_argument("--json", action="store_true", help="write the test report as JSON to stdout")
    fx = add("fix", help="apply the compiler's verified fixes to .gg files")
    fx.add_argument("paths", nargs="*", help="files or directories (default: .)")
    fx.add_argument("--dry-run", action="store_true", help="print the fixes without writing files")
    fx.add_argument("--likely", action="store_true", help="also apply `likely` fixes (verified, but a guess)")
    ck = add("check", help="type-check and report diagnostics (no codegen)")
    ck.add_argument("files", nargs="+", help="source file(s)")
    ck.add_argument("--json", action="store_true", help="write diagnostics as JSON to stdout")

    api_p = add("api", help="list the standard library (signatures and one-line descriptions)")
    api_p.add_argument("--json", action="store_true", help="write the catalog as JSON to stdout")
    api_p.add_argument("--lock", action="store_true", help="write gg.api.lock: this package's public API")
    api_p.add_argument("--check", action="store_true",
                       help="compare this package's public API with gg.api.lock (exit 1 on an unversioned break)")

    ex = add("explain", help="print the explanation of an error code")
    ex.add_argument("code", help="error code, e.g. GG0301")
    ex.add_argument("--json", action="store_true", help="write the explanation as JSON")

    dc = add("doc", help="generate Markdown docs from `#` comments above declarations")
    dc.add_argument("paths", nargs="*", help="files or directories (default: .)")
    dc.add_argument("-o", "--output", help="output .md file (default: DOCS.md or <file>.md, or - for stdout)")
    return p


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    args = build_arg_parser().parse_args(argv)
    _set_color(getattr(args, "color", "auto"))
    global DEBUG_INFO, NATIVE
    DEBUG_INFO = bool(getattr(args, "debug", False))
    NATIVE = None  # set again by the package of this command, if there is one
    DEP_ROOTS.clear()
    try:
        if args.command == "api":
            return cmd_api(args.json, args.lock, args.check)
        if args.command == "explain":
            return cmd_explain(args.code, args.json)
        if args.command == "check":
            return cmd_check(args.files, args.json)
        if args.command == "fix":
            return cmd_fix(args.paths, args.dry_run, args.likely)
        if args.command == "targets":
            return cmd_targets()
        if args.command == "toolchain":
            return cmd_toolchain()
        if args.command == "debug-scripts":
            return cmd_debug_scripts()
        if args.command in ("fetch", "update", "publish"):
            return cmd_packages(args.command, getattr(args, "index", None))
        if args.command in ("new", "fmt", "test", "doc"):
            from . import tools
            if args.command == "new":
                return tools.cmd_new(args.name, args.path)
            if args.command == "fmt":
                return tools.cmd_fmt(args.paths, args.check)
            if args.command == "test":
                return tools.cmd_test(args.paths, args.release, args.json)
            return tools.cmd_doc(args.paths, args.output)
        if args.command in ("build", "run") and not args.files:
            from . import tools
            mp = tools.find_manifest()
            if mp is None:
                print("Error: no source files given and no gg.toml found.", file=sys.stderr)
                return 1
            manifest = tools.load_manifest(mp)
            tools.activate_manifest(manifest)
            args.files = [str(manifest.main)]
            if args.command == "build":
                _warn_api_lock(manifest)
        elif args.command in ("build", "run"):
            from . import tools
            mp = tools.find_manifest(Path(args.files[0]).resolve().parent)
            if mp is not None:
                tools.activate_manifest(tools.load_manifest(mp))
        if args.command == "lsp":
            from .lsp import run_server
            return run_server()
        if args.command == "bindgen":
            from .bindgen import bindgen
            text = _read_source(args.header)
            if text is None:
                return 1
            if args.cpp:
                from .cppbind import cpp_bindgen
                header = Path(args.header)
                out_file = Path(args.output) if args.output else header.with_suffix(".gg")
                module, shim = cpp_bindgen(text, args.header_name or header.name, out_file.stem)
                shim_file = out_file.with_name(f"{out_file.stem}_shim.cpp")
                out_file.write_text(module, encoding="utf-8")
                shim_file.write_text(shim, encoding="utf-8")
                print(f"Bindings written to: {out_file} and {shim_file}")
                print(f'Add to gg.toml:  [native] sources = ["{shim_file.name}"]  (path relative to gg.toml)')
                return 0
            out = bindgen(text, header_name=args.header_name, source_label=Path(args.header).name)
            out_file = args.output or str(Path(args.header).with_suffix(".gg"))
            if out_file == "-":
                sys.stdout.write(out)
            else:
                Path(out_file).write_text(out, encoding="utf-8")
                print(f"Bindings written to: {out_file}")
            return 0
        if args.command == "tokens":
            source = _read_source(args.file)
            if source is None:
                return 1
            lines = [f"{t.line}:{t.col}\t{t.kind}\t{t.text!r}" for t in lex_source(source)]
            content = "\n".join(lines) + "\n"
            if getattr(args, "output", None) and args.output != "-":
                Path(args.output).write_text(content, encoding="utf-8")
                print(f"Tokens written to: {args.output}")
            else:
                sys.stdout.write(content)
            return 0
        if args.command == "ast":
            diags = DiagnosticBag()
            program, sources, diags = load_sources_and_ast(args.files, diags=diags)
            _raise_if_errors(diags)
            ast_str = dump_ast(program)
            if getattr(args, "output", None) and args.output != "-":
                Path(args.output).write_text(ast_str + "\n", encoding="utf-8")
                print(f"AST written to: {args.output}")
            else:
                print(ast_str)
            return 0
        if args.command == "emit-ll":
            return cmd_emit_llvm(args.files, args.release, args.unchecked, None, args.release, args.target,
                                 args.no_std, ir_out=args.output)
        if args.command == "emit-bc":
            out = args.output or str(Path(args.files[0]).with_suffix(".bc"))
            return cmd_emit_llvm(args.files, args.release, args.unchecked, out, args.release, args.target,
                                 args.no_std)
        if args.command in ("build", "run"):
            args.link = args.link + [f"-L{d}" for d in args.link_path] + args.link_file
        if args.command == "build":
            return cmd_build(args.files, args.output, release=args.release, links=args.link,
                             unchecked=args.unchecked, target=args.target, no_std=args.no_std)
        return cmd_run(args.files, release=args.release, links=args.link, unchecked=args.unchecked,
                       target=args.target, no_std=args.no_std)
    except CompileError as err:
        target_f = args.file if hasattr(args, "file") else (args.files[0] if hasattr(args, "files") and args.files else "<source>")
        src = _read_source(target_f) or ""
        _print_diagnostics(err.diagnostics, src, target_f)
        return 1


if __name__ == "__main__":
    sys.exit(main())
