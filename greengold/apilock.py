"""`gg api --lock` / `gg api --check`: a package's public surface, with inferred modes, kept stable.

Parameter modes are inferred from function bodies, so a change inside a body can change what callers
must do (`read` -> `consume` moves their value away). Instead of asking library authors to write every
mode, the package records its public surface in `gg.api.lock` and the compiler compares against it:

    gg api --lock     write gg.api.lock for the package in the current directory
    gg api --check    report changes since the lock; breaking ones fail unless the version allows them

A breaking change needs a new major version (`1.4.0` -> `2.0.0`; below 1.0 a new minor: `0.3.1` -> `0.4.0`).
Compatible changes: a new symbol, a parameter that asks less of the caller (`consume` -> `read`,
`lend` -> `read`), a type that becomes copyable.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .ast_nodes import ConstDecl, EnumDecl, FeatureDecl, FuncDecl, StructDecl, TypeRef

LOCK = "gg.api.lock"
SCHEMA = 1

# A mode change is compatible when every call that compiled before still compiles and means the same.
_COMPATIBLE_MODES = {("consume", "read"), ("lend", "read")}


@dataclass
class Change:
    key: str
    breaking: bool
    message: str


def _norm(ty: object) -> str:
    return str(ty or "void").replace("::", ".")


def _tref(t: TypeRef | None) -> str:
    """A type as written (`TypeRef.name` is the whole text, `Pair[i32, f64]` included)."""
    if t is None:
        return "void"
    return f"{t.qualifier}.{t.name}" if t.qualifier else t.name


def _module_name(path: Path, src: Path) -> str:
    try:
        rel = path.resolve().relative_to(src.resolve())
    except ValueError:
        return path.stem
    return ".".join(rel.with_suffix("").parts)


def surface(files: list[Path], src: Path) -> dict[str, dict]:
    """Public symbols declared in `files`, keyed `module.name` / `module.Type.method`."""
    from .cli import analyze
    from .typeinfo import moves
    out: dict[str, dict] = {}
    wanted = {str(f.resolve()) for f in files}
    for f in files:
        program, _sources, diags, checker = analyze([str(f)], require_main=False)
        if checker is None or diags.has_errors():
            first = next((d for d in diags.items if d.severity == "error"), None)
            raise ValueError(f"{f}: does not compile" + (f": {first.message}" if first else ""))
        structs, enums = program.struct_infos, program.enum_infos
        for d in program.decls:
            fname = getattr(d, "filename", None)
            if not fname or str(Path(fname).resolve()) not in wanted or not getattr(d, "is_pub", False):
                continue
            name = getattr(d, "name", "")
            if not name or name.startswith("_") or getattr(d, "from_prelude", False):
                continue
            mod = _module_name(Path(fname), src)
            if isinstance(d, FuncDecl):
                if d.is_test or getattr(d, "is_lambda", False) or (d.name == "main" and d.owner is None):
                    continue
                if d.owner is None and name.startswith("test_") and not d.params and d.ret is None:
                    continue  # `fn test_x():` is a test
                if d.owner and d.owner.split("::")[-1].startswith("_"):
                    continue
                owner = d.owner.split("::")[-1] if d.owner else None
                key = f"{mod}.{owner}.{name}" if owner else f"{mod}.{name}"
                generic = bool(d.type_params or d.owner_params)
                params = []
                for p in d.params:
                    ty = _tref(p.type_ref) if generic else _norm(getattr(p, "ty", None) or _tref(p.type_ref))
                    mode = p.mode or ("copy" if not generic else "")
                    params.append({"name": p.name, "type": ty, "mode": mode})
                ret = _tref(d.ret) if generic else _norm(getattr(d, "ret_ty", None) or _tref(d.ret))
                out[key] = {"kind": "fn", "params": params, "ret": ret,
                            "type_params": list(d.type_params or d.owner_params)}
            elif isinstance(d, StructDecl):
                key = f"{mod}.{name}"
                canon = next((k for k, v in structs.items() if v.decl is d), None)
                info = structs.get(canon) if canon else None
                fields = {}
                all_pub = True
                for fd in d.fields:
                    pub = bool(getattr(fd, "is_pub", False)) if info is None else info.field_pub.get(fd.name, False)
                    all_pub = all_pub and pub
                    if pub:
                        fields[fd.name] = _norm(getattr(fd, "ty", None) or _tref(fd.type_ref))
                out[key] = {"kind": "struct", "fields": fields, "constructible": all_pub,
                            "moves": bool(canon and moves(canon, structs, enums)),
                            "type_params": list(d.type_params)}
            elif isinstance(d, EnumDecl):
                key = f"{mod}.{name}"
                canon = next((k for k, v in enums.items() if v.decl is d), None)
                variants = {v.name: [_tref(t) for t in v.payload] for v in d.variants}
                out[key] = {"kind": "enum", "variants": variants,
                            "moves": bool(canon and moves(canon, structs, enums)),
                            "type_params": list(d.type_params)}
            elif isinstance(d, FeatureDecl):
                out[f"{mod}.{name}"] = {"kind": "feature",
                                        "required": sorted(m.name for m in d.methods if not m.body),
                                        "provided": sorted(m.name for m in d.methods if m.body)}
            elif isinstance(d, ConstDecl):
                out[f"{mod}.{name}"] = {"kind": "const", "type": _norm(getattr(d, "ty", None) or _tref(d.type_ref))}
    return dict(sorted(out.items()))


def _sig(entry: dict) -> str:
    if entry["kind"] != "fn":
        return entry["kind"]
    ps = ", ".join(f"{p['name']}: {'' if p['mode'] in ('', 'copy') else p['mode'] + ' '}{p['type']}"
                   for p in entry["params"])
    return f"fn({ps}) -> {entry['ret']}"


def diff(old: dict[str, dict], new: dict[str, dict]) -> list[Change]:
    out: list[Change] = []
    for key, was in old.items():
        now = new.get(key)
        if now is None:
            out.append(Change(key, True, f"`{key}` was removed"))
            continue
        if now["kind"] != was["kind"]:
            out.append(Change(key, True, f"`{key}` changed from a {was['kind']} to a {now['kind']}"))
            continue
        out.extend(_diff_entry(key, was, now))
    for key in new:
        if key not in old:
            out.append(Change(key, False, f"`{key}` was added"))
    return out


def _diff_entry(key: str, was: dict, now: dict) -> list[Change]:
    out: list[Change] = []
    kind = was["kind"]
    if kind == "fn":
        if len(was["params"]) != len(now["params"]) or was["ret"] != now["ret"] or \
                any(a["type"] != b["type"] for a, b in zip(was["params"], now["params"])):
            return [Change(key, True, f"`{key}` changed its signature: `{_sig(was)}` is now `{_sig(now)}`")]
        for a, b in zip(was["params"], now["params"]):
            if a["mode"] == b["mode"]:
                continue
            breaking = (a["mode"], b["mode"]) not in _COMPATIBLE_MODES
            why = {"consume": "callers' values are now moved away",
                   "lend": "callers must now pass a variable that can change",
                   "read": "callers keep their values"}.get(b["mode"], "")
            msg = f"parameter `{b['name']}` of `{key}` is now `{b['mode']}` (was `{a['mode']}`)"
            if why:
                msg += f": {why}"
            if breaking:
                msg += ". The mode is inferred from the body, so a change inside the function changed it"
            out.append(Change(key, breaking, msg))
    elif kind == "struct":
        for f, ty in was["fields"].items():
            if f not in now["fields"]:
                out.append(Change(key, True, f"public field `{key}.{f}` was removed or made private"))
            elif now["fields"][f] != ty:
                out.append(Change(key, True, f"field `{key}.{f}` changed type: `{ty}` is now `{now['fields'][f]}`"))
        added = [f for f in now["fields"] if f not in was["fields"]]
        if added and was["constructible"]:
            out.append(Change(key, True, f"`{key}` gained field(s) {', '.join(added)}: literals that write "
                                         "every field no longer compile"))
        elif added:
            out.append(Change(key, False, f"`{key}` gained public field(s) {', '.join(added)}"))
        if was["constructible"] and not now["constructible"]:
            out.append(Change(key, True, f"`{key}` can no longer be built with a literal (a field became private)"))
    elif kind == "enum":
        for v, payload in was["variants"].items():
            if v not in now["variants"]:
                out.append(Change(key, True, f"variant `{key}.{v}` was removed"))
            elif now["variants"][v] != payload:
                out.append(Change(key, True, f"variant `{key}.{v}` changed its payload"))
        added = [v for v in now["variants"] if v not in was["variants"]]
        if added:
            out.append(Change(key, True, f"`{key}` gained variant(s) {', '.join(added)}: a `match` that "
                                         "lists every variant no longer covers them"))
    elif kind == "feature":
        new_req = set(now["required"]) - set(was["required"])
        if new_req:
            out.append(Change(key, True, f"feature `{key}` now requires {', '.join(sorted(new_req))}"))
        gone = (set(was["required"]) | set(was["provided"])) - (set(now["required"]) | set(now["provided"]))
        if gone:
            out.append(Change(key, True, f"feature `{key}` no longer has {', '.join(sorted(gone))}"))
    elif kind == "const" and was["type"] != now["type"]:
        out.append(Change(key, True, f"constant `{key}` changed type: `{was['type']}` is now `{now['type']}`"))
    if kind in ("struct", "enum") and was.get("moves") != now.get("moves"):
        out.append(Change(key, bool(now.get("moves")),
                          f"`{key}` is now {'moved, not copied' if now.get('moves') else 'copied'}"
                          + (" (it gained a heap field, a handle, or `drop`)" if now.get("moves") else "")))
    if was.get("type_params") != now.get("type_params") and kind in ("fn", "struct", "enum"):
        out.append(Change(key, True, f"`{key}` changed its type parameters"))
    return out


def _version(v: str) -> tuple[int, int, int]:
    parts = (v.split("-")[0].split("+")[0].split(".") + ["0", "0", "0"])[:3]
    try:
        return int(parts[0]), int(parts[1]), int(parts[2])
    except ValueError:
        return 0, 0, 0


def allows_breaking(locked: str, current: str) -> bool:
    """Semver: a breaking change needs a new major version, or a new minor one below 1.0."""
    a, b = _version(locked), _version(current)
    if b[0] != a[0]:
        return b[0] > a[0]
    return a[0] == 0 and b[1] > a[1]


def package_files(root: Path) -> tuple[list[Path], Path]:
    src = root / "src"
    base = src if src.is_dir() else root
    files = sorted(p for p in base.rglob("*.gg") if ".gg-cache" not in p.parts)
    return files, base


def write_lock(root: Path, name: str, version: str) -> Path:
    files, src = package_files(root)
    doc = {"schema": SCHEMA, "package": name, "version": version, "symbols": surface(files, src)}
    path = root / LOCK
    path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    return path


def check_lock(root: Path, version: str) -> tuple[list[Change], str] | None:
    """Changes since the lock and the locked version, or None when there is no lock."""
    path = root / LOCK
    if not path.is_file():
        return None
    doc = json.loads(path.read_text(encoding="utf-8"))
    files, src = package_files(root)
    return diff(doc.get("symbols", {}), surface(files, src)), str(doc.get("version", "0.0.0"))
