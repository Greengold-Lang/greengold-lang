"""Standard library catalog for `gg api`.

Symbols come from `greengold/core/core.gg`, `greengold/std/*.gg`, and the compiler
builtins that have no source declaration (`print`, `List`, pointer intrinsics).
"""
from __future__ import annotations

import json
from pathlib import Path

from . import __version__
from .ast_nodes import (
    ConstDecl, EnumDecl, ExternFuncDecl, FeatureDecl, FuncDecl, StructDecl,
)
from .diagnostics import DiagnosticBag
from .lexer import tokenize
from .parser import parse

ROOT = Path(__file__).parent
CORE = ROOT / "core" / "core.gg"
STD = ROOT / "std"


def library() -> dict:
    symbols: list[dict] = []
    symbols.extend(_builtins())
    symbols.extend(_file("core", CORE))
    for path in sorted(STD.glob("*.gg")):
        symbols.extend(_file(f"std.{path.stem}", path))
    return {
        "schema_version": 1,
        "tool": {"name": "gg", "version": __version__},
        "symbols": symbols,
    }


def library_text(doc: dict | None = None) -> str:
    doc = doc or library()
    lines: list[str] = []
    current = None
    for sym in doc["symbols"]:
        if sym["module"] != current:
            current = sym["module"]
            if lines:
                lines.append("")
            lines.append(f"# {current}")
        lines.append(sym["signature"])
        if sym["description"]:
            lines.append(f"    {sym['description']}")
    lines.append("")
    return "\n".join(lines)


def library_json(doc: dict | None = None) -> str:
    return json.dumps(doc or library(), indent=2) + "\n"


def _file(module: str, path: Path) -> list[dict]:
    text = path.read_text(encoding="utf-8-sig")
    diags = DiagnosticBag()
    program = parse(tokenize(text, diags), diags, filename=str(path))
    if diags.has_errors():
        raise RuntimeError(f"{path} did not parse: {diags.items[0].message}")
    notes = _comments(text)
    out: list[dict] = []
    for decl in program.decls:
        if module != "core" and not getattr(decl, "is_pub", False):
            continue
        if getattr(decl, "name", "").startswith("_") or getattr(decl, "name", "").startswith("__"):
            continue
        if isinstance(decl, FuncDecl):
            if decl.owner and decl.owner.startswith("_"):
                continue
            out.append(_sym(module, _fn_name(decl), "fn", _fn_sig(decl), notes.get(decl.line, "")))
        elif isinstance(decl, StructDecl):
            out.append(_sym(module, decl.name, "struct", _struct_sig(decl), notes.get(decl.line, "")))
        elif isinstance(decl, EnumDecl):
            out.append(_sym(module, decl.name, "enum", _enum_sig(decl), notes.get(decl.line, "")))
        elif isinstance(decl, FeatureDecl):
            out.append(_sym(module, decl.name, "feature", _feature_sig(decl), notes.get(decl.line, "")))
        elif isinstance(decl, ConstDecl):
            sig = f"const {decl.name}"
            if decl.type_ref is not None:
                sig += f": {decl.type_ref.name}"
            out.append(_sym(module, decl.name, "const", sig, notes.get(decl.line, "")))
        elif isinstance(decl, ExternFuncDecl):
            out.append(_sym(module, decl.name, "extern", _extern_sig(decl), notes.get(decl.line, "")))
    return out


def _sym(module: str, name: str, kind: str, signature: str, description: str) -> dict:
    return {
        "module": module,
        "name": name,
        "kind": kind,
        "signature": signature,
        "description": _sentence(description),
    }


def _comments(text: str) -> dict[int, str]:
    """Map a declaration's line to the comment block touching it."""
    pending: list[str] = []
    found: dict[int, str] = {}
    for lineno, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if stripped.startswith("#") and not stripped.startswith("#!"):
            pending.append(stripped[1:].strip())
            continue
        if stripped == "":
            pending = []
            continue
        if pending:
            found[lineno] = " ".join(part for part in pending if part)
        pending = []
    return found


def _sentence(text: str) -> str:
    text = " ".join(text.split())
    if not text or set(text) <= {"-"}:
        return ""
    for mark in (". ", "; "):
        cut = text.find(mark)
        if 0 < cut < 180:
            return text[:cut + 1]
    return text if len(text) <= 180 else text[:177].rstrip() + "..."


def _params(names: list[str], bounds: dict) -> str:
    if not names:
        return ""
    return "[" + ", ".join(_one_param(name, bounds) for name in names) + "]"


def _one_param(name: str, bounds: dict) -> str:
    items = bounds.get(name) or []
    if not items:
        return name
    shown = " + ".join(getattr(item, "name", str(item)) for item in items)
    return f"{name}: {shown}"


def _fn_name(decl: FuncDecl) -> str:
    return f"{decl.owner}.{decl.name}" if decl.owner else decl.name


def _fn_sig(decl: FuncDecl) -> str:
    prefix = ""
    if decl.is_comptime:
        prefix += "comptime "
    if decl.is_hot:
        prefix += "hot "
    params = ", ".join(_param(p) for p in decl.params)
    ret = ""
    if decl.ret is not None:
        if decl.ret_view:
            word = "lend" if decl.ret_lend else "ref"
            ret = f" -> {word} {decl.ret.name}"
            if decl.ret_tied:
                ret += f" tied to {decl.ret_tied}"
        else:
            ret = f" -> {decl.ret.name}"
    overflow = f" overflow: {decl.overflow_mode}" if decl.overflow_mode else ""
    owner = f"{decl.owner}." if decl.owner else ""
    generics = _params(decl.type_params, decl.bounds)
    return f"{prefix}fn {owner}{decl.name}{generics}({params}){ret}{overflow}"


def _param(p) -> str:
    if p.name == "self" and p.mode == "" and p.type_ref.name == "Self":
        return "self"
    text = f"{p.name}: "
    if p.exclusive:
        text += "exclusive "
    if p.mode:
        text += p.mode + " "
    text += p.type_ref.name
    if p.tied_to:
        text += f" tied to {p.tied_to}"
    return text


def _struct_sig(decl: StructDecl) -> str:
    prefix = "extern " if decl.is_extern else ""
    fields = ", ".join(_field(f) for f in decl.fields)
    return f"{prefix}struct {decl.name}{_params(decl.type_params, decl.bounds)} {{ {fields} }}"


def _field(f) -> str:
    text = f"{f.name}: "
    if f.mode:
        text += f.mode + " "
    text += f.type_ref.name
    if f.tied_to:
        text += f" tied to {f.tied_to}"
    return text


def _enum_sig(decl: EnumDecl) -> str:
    variants = []
    for variant in decl.variants:
        if variant.payload:
            variants.append(variant.name + "(" + ", ".join(t.name for t in variant.payload) + ")")
        else:
            variants.append(variant.name)
    return f"enum {decl.name}{_params(decl.type_params, decl.bounds)} {{ {', '.join(variants)} }}"


def _feature_sig(decl: FeatureDecl) -> str:
    methods = "; ".join(_fn_sig(m) for m in decl.methods)
    return f"feature {decl.name} {{ {methods} }}"


def _extern_sig(decl: ExternFuncDecl) -> str:
    header = f'"{decl.header}" ' if decl.header else ""
    params = ", ".join(_param(p) for p in decl.params)
    if decl.variadic:
        params = params + ", ..." if params else "..."
    ret = f" -> {decl.ret.name}" if decl.ret is not None else ""
    return f"extern {header}fn {decl.name}({params}){ret}"


def _builtins() -> list[dict]:
    rows = [
        ("print", "fn print(...)", "Print numbers, bool, str, or string, separated by spaces, then a newline."),
        ("eprint", "fn eprint(...)", "Like print, but write to the standard error stream."),
        ("panic", "fn panic(message: str)", "Stop the program with a message: a `str` or `string`, such as an f-string."),
        ("input", "fn input(prompt: str) -> str", "Read a line. The prompt is optional: `input()` or `input(\"prompt\")`."),
        ("List", "struct List[T]", "Owned growable array. `List[T]()` is empty. `.len` is the length. `push`, `pop`, `clear`, `reserve`, `resize`, `truncate`, `swap`, `swap_remove`, `remove` and `insert` need a list that is not `fixed`. `get` returns `ref T`. Copied elements also have `map`, `filter`, `fold`, `any`, `all`, `count`, `find`, `position`, `contains`, `index_of`, `sum`, `min`, `max`, `first`, `last`, `is_empty`, `reverse`, `extend`, `sort`, and `sort_by`."),
        ("Box", "struct Box[T]", "Owned heap slot. `Box[T](value)` stores one value. Read and write it as `.value`."),
        ("Fn", "type Fn(A) -> R", "Owned closure value: returned, stored, called as `f(x)`. `.clone()` shares it. A lambda written where a `Fn` is expected owns its captures."),
        ("Shared", "struct Shared[T]", "Reference-counted heap value. `Shared[T](value)`; `.clone()` adds an owner; `.value` is read-only. Not for sharing between threads."),
        ("Arc", "struct Arc[T]", "`Shared[T]` with an atomic count: `Arc[T](value)`; `.clone()` adds an owner from any thread; `.value` is read-only. It crosses threads when `T` can be shared."),
        ("clone", "fn clone[T](self: read T) -> T", "Deep copy of a value (`x.clone()`). For `Shared[T]` it adds an owner instead."),
        ("hash", "fn hash[T](x: T) -> u64", "Hash of an integer, `bool`, text, or a struct, enum, or list of them (field by field), or through the type's own `fn hash(self: Self) -> u64`."),
        ("to_json", "fn to_json[T](x: T) -> string", "JSON text of a value: structs are objects, enums `\"Name\"` or `{\"Name\": payload}`, `Optional` a value or `null`, lists, arrays, and tuples arrays."),
        ("from_json", "fn from_json[T](text: str) -> Result[T, string]", "Reads a value of type `T` from JSON text, the form `to_json` writes. Unknown keys are skipped; a missing `Optional` field is `None`."),
        ("to_string", "fn to_string[T](self: T) -> string", "The text `print` writes for the value (`p.to_string()`); a type's own `to_string` wins."),
        ("str.len", "fn str.len(self: read str) -> usize", "Byte length of a string view. Also written `s.len`."),
        ("str.to_string", "fn str.to_string(self: read str) -> string", "Copy a view into an owned `string`."),
        ("add_overflows", "fn add_overflows[T: Int](a: T, b: T) -> bool", "True when `a + b` does not fit in `T`."),
        ("sub_overflows", "fn sub_overflows[T: Int](a: T, b: T) -> bool", "True when `a - b` does not fit in `T`."),
        ("mul_overflows", "fn mul_overflows[T: Int](a: T, b: T) -> bool", "True when `a * b` does not fit in `T`."),
        ("max_value", "fn max_value[T: Int]() -> T", "Largest value of an integer type."),
        ("min_value", "fn min_value[T: Int]() -> T", "Smallest value of an integer type."),
        ("addr", "fn addr(place) -> *T", "Address of a place. Only inside `unsafe:`."),
        ("addr_mut", "fn addr_mut(place) -> *mut T", "Mutable address of a place that is not `fixed`. Only inside `unsafe:`."),
        ("ptr_cast", "fn ptr_cast[*T](p) -> *T", "Cast one pointer type to another. Only inside `unsafe:`."),
        ("ptr_offset", "fn ptr_offset(p: *T, n: isize) -> *T", "Move a pointer by `n` elements. Only inside `unsafe:`."),
        ("ptr_to_int", "fn ptr_to_int(p) -> usize", "Pointer bits as `usize`. Only inside `unsafe:`."),
        ("int_to_ptr", "fn int_to_ptr[*T](n: usize) -> *T", "Integer bits as a pointer. Only inside `unsafe:`."),
        ("cstr_to_string", "fn cstr_to_string(p: *u8) -> str", "View a NUL-terminated C string. Only inside `unsafe:`."),
        ("string_to_cstr", "fn string_to_cstr(s: str) -> *u8", "Temporary NUL-terminated pointer for a `str`. Only inside `unsafe:`."),
        ("str_from_raw", "fn str_from_raw(p: *u8, len: usize) -> str", "View `len` bytes. The view is not NUL-terminated. Only inside `unsafe:`."),
        ("Num", "feature Num", "Numbers: integers and floats."),
        ("Int", "feature Int", "Integer types."),
        ("Float", "feature Float", "f32 and f64."),
        ("Ord", "feature Ord", "Numbers and text, which can be ordered with `<` and `>`."),
        ("Eq", "feature Eq", "Numbers, bool, and str, which can be compared with `==`."),
    ]
    return [_sym("builtin", name, "builtin", sig, desc) for name, sig, desc in rows]
