"""Assurance tools: what is in a build, whether it is the same twice, and where the unsafe code is.

    gg sbom app.gg                     # software bill of materials (CycloneDX 1.5 JSON); --format spdx for SPDX 2.3
    gg repro app.gg                    # builds twice, in different directories, and compares the bytes
    gg unsafe-audit app.gg             # every `unsafe:` block, `asm`, foreign function, and `static`, with its place

The bill of materials lists the compiler and the LLVM it carries, the program's own source files and the standard library modules
it imports, each with a SHA-256, and the dependencies pinned in `gg.lock`. Nothing in it depends on the time or the machine unless
you ask for a timestamp (`--timestamp`), so the same sources and compiler give the same file, and a reviewer can diff two of them.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _is_library(path: Path) -> bool:
    try:
        return PACKAGE_DIR in path.resolve().parents
    except OSError:
        return False


def gather(files: list[str]):
    """(sources, locks): the loaded source files and the dependencies in gg.lock, or None when the front end fails."""
    from .cli import analyze
    program, sources, diags, _checker = analyze(files)
    if diags.has_errors():
        return None
    locks: list[dict] = []
    for start in (Path(files[0]).resolve().parent, Path.cwd()):
        lock = start / "gg.lock"
        if lock.is_file():
            try:
                import tomllib
            except ModuleNotFoundError:  # Python 3.10
                import tomli as tomllib
            doc = tomllib.loads(lock.read_text(encoding="utf-8"))
            locks = list(doc.get("package", []))
            break
    return program, sources, locks


def _tool_versions() -> list[dict]:
    from . import __version__
    out = [{"type": "application", "name": "greengold", "version": __version__, "purl": f"pkg:pypi/greengold@{__version__}"}]
    try:
        import llvmlite
        out.append({"type": "library", "name": "llvmlite", "version": llvmlite.__version__,
                    "purl": f"pkg:pypi/llvmlite@{llvmlite.__version__}"})
        import llvmlite.binding as llvm
        out.append({"type": "library", "name": "llvm", "version": ".".join(str(x) for x in llvm.llvm_version_info)})
    except Exception:
        pass
    return out


def build_sbom(files: list[str], fmt: str = "cyclonedx", timestamp: bool = False, name: str | None = None) -> dict | None:
    found = gather(files)
    if found is None:
        return None
    _program, sources, locks = found
    app = name or Path(files[0]).stem
    own, library = [], []
    for fname, text in sorted(sources.items()):
        p = Path(fname)
        data = text.encode("utf-8")
        if p.name.startswith("<"):
            continue
        entry = {"path": p.as_posix() if _is_library(p) is False else None, "sha256": _sha256(data)}
        if _is_library(p):
            rel = p.resolve().relative_to(PACKAGE_DIR).as_posix()
            library.append({"name": "std." + Path(rel).stem if rel.startswith("std/") else rel, "sha256": entry["sha256"]})
        else:
            try:
                shown = p.resolve().relative_to(Path.cwd().resolve()).as_posix()
            except ValueError:
                shown = p.name
            own.append({"name": shown, "sha256": entry["sha256"]})
    tools = _tool_versions()
    version = tools[0]["version"]
    seed = json.dumps([own, library, locks, tools], sort_keys=True).encode()
    serial = f"urn:uuid:{hashlib.sha256(seed).hexdigest()[:8]}-{hashlib.sha256(seed).hexdigest()[8:12]}-" \
             f"{hashlib.sha256(seed).hexdigest()[12:16]}-{hashlib.sha256(seed).hexdigest()[16:20]}-{hashlib.sha256(seed).hexdigest()[20:32]}"
    if fmt == "spdx":
        pkgs = [{"SPDXID": "SPDXRef-App", "name": app, "downloadLocation": "NOASSERTION", "filesAnalyzed": True,
                 "licenseConcluded": "NOASSERTION", "licenseDeclared": "NOASSERTION", "copyrightText": "NOASSERTION"}]
        spdx_files = []
        for i, f in enumerate(own + library):
            spdx_files.append({"SPDXID": f"SPDXRef-File{i}", "fileName": f["name"], "checksums": [
                {"algorithm": "SHA256", "checksumValue": f["sha256"]}], "licenseConcluded": "NOASSERTION",
                "copyrightText": "NOASSERTION", "licenseInfoInFiles": ["NOASSERTION"]})
        rels = [{"spdxElementId": "SPDXRef-DOCUMENT", "relationshipType": "DESCRIBES", "relatedSpdxElement": "SPDXRef-App"}]
        for i, t in enumerate(tools):
            pkgs.append({"SPDXID": f"SPDXRef-Tool{i}", "name": t["name"], "versionInfo": t["version"],
                         "downloadLocation": "NOASSERTION", "filesAnalyzed": False, "licenseConcluded": "NOASSERTION",
                         "licenseDeclared": "NOASSERTION", "copyrightText": "NOASSERTION"})
            rels.append({"spdxElementId": "SPDXRef-App", "relationshipType": "BUILD_TOOL_OF" if False else "DEPENDS_ON",
                         "relatedSpdxElement": f"SPDXRef-Tool{i}"})
        for i, d in enumerate(locks):
            pkgs.append({"SPDXID": f"SPDXRef-Dep{i}", "name": d.get("name", "?"), "versionInfo": d.get("version", d.get("commit", "")),
                         "downloadLocation": d.get("url", "NOASSERTION"), "filesAnalyzed": False,
                         "licenseConcluded": "NOASSERTION", "licenseDeclared": "NOASSERTION", "copyrightText": "NOASSERTION"})
            rels.append({"spdxElementId": "SPDXRef-App", "relationshipType": "DEPENDS_ON", "relatedSpdxElement": f"SPDXRef-Dep{i}"})
        doc = {"spdxVersion": "SPDX-2.3", "dataLicense": "CC0-1.0", "SPDXID": "SPDXRef-DOCUMENT", "name": app,
               "documentNamespace": f"https://greengoldlang.com/sbom/{app}/{serial[9:]}",
               "creationInfo": {"creators": [f"Tool: greengold-{version}"],
                                "created": _now() if timestamp else "1970-01-01T00:00:00Z"},
               "packages": pkgs, "files": spdx_files, "relationships": rels}
        return doc
    components = []
    for t in tools[1:]:
        c = {"type": t["type"], "name": t["name"], "version": t["version"]}
        if "purl" in t:
            c["purl"] = t["purl"]
        components.append(c)
    for f in own:
        components.append({"type": "file", "name": f["name"], "hashes": [{"alg": "SHA-256", "content": f["sha256"]}]})
    for f in library:
        components.append({"type": "library", "name": f["name"], "version": version,
                           "hashes": [{"alg": "SHA-256", "content": f["sha256"]}], "scope": "required",
                           "description": "Greengold standard library module"})
    for d in locks:
        c = {"type": "library", "name": d.get("name", "?"), "version": d.get("version") or d.get("commit", "")}
        if d.get("url"):
            c["externalReferences"] = [{"type": "vcs" if d.get("source") == "git" else "distribution", "url": d["url"]}]
        components.append(c)
    meta = {"component": {"type": "application", "name": app, "version": "unversioned"},
            "tools": {"components": [{"type": "application", "name": "greengold", "version": version}]}}
    if timestamp:
        meta["timestamp"] = _now()
    return {"bomFormat": "CycloneDX", "specVersion": "1.5", "serialNumber": serial, "version": 1, "metadata": meta,
            "components": components}


def _now() -> str:
    import datetime
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def cmd_sbom(files: list[str], fmt: str, output: str | None, timestamp: bool) -> int:
    doc = build_sbom(files, fmt, timestamp)
    if doc is None:
        print("Error: the program does not compile, so its contents are not known.", file=sys.stderr)
        return 1
    text = json.dumps(doc, indent=2, sort_keys=False) + "\n"
    if output:
        Path(output).write_text(text, encoding="utf-8")
        print(f"SBOM ({fmt}) written to {output}")
    else:
        sys.stdout.write(text)
    return 0


# -- unsafe audit ----------------------------------------------------------------------------------------------------

def audit(files: list[str]) -> list[dict] | None:
    from .ast_nodes import AllocatorDecl, Call, ConstDecl, ExternFuncDecl, FuncDecl, If, walk
    found = gather(files)
    if found is None:
        return None
    program, _sources, _locks = found
    out: list[dict] = []

    def add(kind: str, node, where: str, detail: str = "", fallback: str | None = None) -> None:
        out.append({"kind": kind, "file": getattr(node, "filename", None) or fallback, "line": node.line, "in": where,
                    "detail": detail})

    for d in program.decls:
        if getattr(d, "from_prelude", False):
            continue
        fn = getattr(d, "filename", None)
        if fn and _is_library(Path(fn)):
            continue
        if isinstance(d, ExternFuncDecl):
            add("foreign-function", d, "(module)", d.name)
        elif isinstance(d, AllocatorDecl):
            add("custom-allocator", d, "(module)", f"{d.alloc}, {d.resize}, {d.free}")
        elif isinstance(d, ConstDecl) and getattr(d, "is_static", False):
            add("static", d, "(module)", d.name)
            for a in d.attrs:
                add("attribute", a, d.name, "@" + a.name, d.filename)
        elif isinstance(d, FuncDecl) and d.body is not None and not d.is_test and d.inst_key is None \
                and not getattr(d, "from_feature_default", False) and not getattr(d, "archetype_stub", False):
            where = f"{d.owner}.{d.name}" if d.owner else d.name
            for a in d.attrs:
                if a.name in ("export", "interrupt", "naked", "section", "weak", "used", "panic_handler"):
                    add("attribute", a, where, "@" + a.name, d.filename)
            for n in walk(d.body):
                if isinstance(n, If) and n.unsafe:
                    add("unsafe-block", n, where, "", d.filename)
                elif isinstance(n, Call) and n.callee == "asm":
                    add("inline-asm", n, where, "", d.filename)
    out.sort(key=lambda r: (r["file"] or "", r["line"]))
    return out


def cmd_audit(files: list[str], as_json: bool) -> int:
    rows = audit(files)
    if rows is None:
        print("Error: the program does not compile.", file=sys.stderr)
        return 1
    if as_json:
        json.dump({"unsafe_uses": rows, "count": len(rows)}, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0
    for r in rows:
        extra = f"  {r['detail']}" if r["detail"] else ""
        print(f"{r['file']}:{r['line']}: {r['kind']} in {r['in']}{extra}")
    print(f"{len(rows)} use(s) of unsafe features in the program's own code")
    return 0


# -- reproducible builds -----------------------------------------------------------------------------------------------

def cmd_repro(files: list[str], release: bool, target: str | None) -> int:
    """Builds the program twice from copies in different directories, with different working directories, and compares."""
    found = gather(files)
    if found is None:
        print("Error: the program does not compile.", file=sys.stderr)
        return 1
    _program, sources, _locks = found
    entry = Path(files[0]).resolve()
    own = [Path(f).resolve() for f in sources if not Path(f).name.startswith("<") and not _is_library(Path(f))]
    root = Path(os.path.commonpath([str(p.parent) for p in own] + [str(entry.parent)]))
    hashes: list[str] = []
    sizes: list[int] = []
    with tempfile.TemporaryDirectory(prefix="gg_repro_") as tmp:
        for label in ("alpha_one", "beta_two_longer_name"):
            dest = Path(tmp) / label / "src"
            for p in own:
                rel = p.relative_to(root)
                (dest / rel).parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(p, dest / rel)
            out = Path(tmp) / label / ("app.exe" if os.name == "nt" else "app")
            cmd = [sys.executable, "-m", "greengold", "build", str(dest / entry.relative_to(root)), "-o", str(out)]
            if release:
                cmd.append("--release")
            if target:
                cmd += ["--target", target]
            env = dict(os.environ)
            env["GG_REPRO"] = "1"
            r = subprocess.run(cmd, capture_output=True, text=True, cwd=str(Path(tmp) / label), env=env)
            produced = out if out.is_file() else out.with_suffix(".o")
            if r.returncode not in (0, 3) or not produced.is_file():
                print(f"Error: the build in {label} failed:\n{r.stderr or r.stdout}", file=sys.stderr)
                return 1
            data = produced.read_bytes()
            hashes.append(_sha256(data))
            sizes.append(len(data))
            time_gap = 0
    if hashes[0] == hashes[1]:
        print(f"reproducible: both builds are {sizes[0]} bytes, SHA-256 {hashes[0]}")
        return 0
    print(f"NOT reproducible: {hashes[0]} ({sizes[0]} bytes) vs {hashes[1]} ({sizes[1]} bytes)", file=sys.stderr)
    return 1
