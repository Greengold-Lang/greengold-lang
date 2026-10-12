"""Help for the person at the keyboard: name suggestions, mechanical fixes, and the few implicit
conversions that cannot lose information.

Every suggestion that has one obvious edit carries it as a `Fix`. `gg check` verifies each fix by applying
it to a copy of the file; `gg fix` and the editor apply the verified ones.
"""
from __future__ import annotations

import copy
import difflib
from functools import lru_cache

from .ast_nodes import Cast, Expr, FieldAccess, MethodCall, Name, Node
from .diagnostics import Edit, Fix
from .typeinfo import INT_RANGES

# Conversions that keep every value: a smaller integer into a wider one, an integer into a float that holds
# it exactly, `f32` into `f64`. `isize`/`usize` are 64-bit on every supported host.
WIDENS: dict[str, frozenset[str]] = {
    "i8": frozenset({"i16", "i32", "i64", "isize", "f32", "f64"}),
    "i16": frozenset({"i32", "i64", "isize", "f32", "f64"}),
    "i32": frozenset({"i64", "isize", "f64"}),
    "i64": frozenset({"isize"}),
    "isize": frozenset({"i64"}),
    "u8": frozenset({"u16", "u32", "u64", "usize", "i16", "i32", "i64", "isize", "f32", "f64"}),
    "u16": frozenset({"u32", "u64", "usize", "i32", "i64", "isize", "f32", "f64"}),
    "u32": frozenset({"u64", "usize", "i64", "isize", "f64"}),
    "u64": frozenset({"usize"}),
    "usize": frozenset({"u64"}),
    "f32": frozenset({"f64"}),
}

# Words people bring from other languages, and the Greengold word.
NAME_SYNONYMS = {
    "True": "true", "False": "false", "Some": "Valid", "nil": "None", "Nothing": "None",
    "println": "print", "printf": "print", "puts": "print", "echo": "print", "printLn": "print",
}
TYPE_SYNONYMS = {
    "String": "string", "Option": "Optional", "Maybe": "Optional", "Vec": "List", "ArrayList": "List",
    "char": "u8", "byte": "u8", "boolean": "bool", "Bool": "bool", "Boolean": "bool",
    "Int": "i32", "Integer": "i32", "Long": "i64", "Float": "f32", "Double": "f64", "number": "f64",
    "int8": "i8", "int16": "i16", "int32": "i32", "int64": "i64",
    "uint8": "u8", "uint16": "u16", "uint32": "u32", "uint64": "u64",
    "float32": "f32", "float64": "f64", "size_t": "usize",
}
METHOD_SYNONYMS = {
    "append": "push", "add": "push", "push_back": "push", "pushBack": "push", "pop_back": "pop",
    "length": "len", "size": "len", "count": "len", "remove_at": "remove", "removeAt": "remove",
    "insert_at": "insert", "includes": "contains", "indexOf": "index_of", "find_index": "position", "findIndex": "position",
    "reduce": "fold", "where": "filter", "select": "map", "every": "all", "some": "any", "sorted": "sort",
    "toString": "to_string", "to_str": "as_str", "str": "as_str",
}


def edit_distance(a: str, b: str) -> int:
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def nearest(word: str, candidates, synonyms: dict[str, str] | None = None) -> str | None:
    """The candidate the author most likely meant, or None."""
    pool = sorted({c for c in candidates if c and c != word and not c.startswith("__")})
    if synonyms and word in synonyms and synonyms[word] in pool:
        return synonyms[word]
    lower = [c for c in pool if c.lower() == word.lower()]
    if lower:
        return lower[0]
    close = difflib.get_close_matches(word, pool, n=1, cutoff=0.55)
    if close:
        return close[0]
    limit = 1 if len(word) < 6 else 2
    ranked = sorted((edit_distance(word, c), c) for c in pool if abs(len(c) - len(word)) <= limit)
    if ranked and ranked[0][0] <= limit and len(word) >= 3:
        return ranked[0][1]
    return None


def rename_fix(line: int, col: int, old: str, new: str, filename: str | None,
               applicability: str = "likely") -> Fix:
    return Fix(f"Replace `{old}` with `{new}`", applicability, [Edit(line, col, line, col + len(old), new, filename)])


def span_end(node: Node) -> tuple[int, int] | None:
    """End column (exclusive) of a node written on one line, else None."""
    if node.length <= 0:
        return None
    return node.line, node.col + node.length


def wrap_fix(node: Node, before: str, after: str, description: str, applicability: str = "likely") -> list[Fix]:
    """`before` + node + `after`, e.g. `i32(` ... `)`. Only for a node on one line."""
    end = span_end(node)
    if end is None:
        return []
    fname = getattr(node, "filename", None)
    edits = [Edit(node.line, node.col, node.line, node.col, before, fname)]
    if after:
        edits.append(Edit(end[0], end[1], end[0], end[1], after, fname))
    return [Fix(description, applicability, edits)]


def _location(node: Node) -> dict:
    return {"line": node.line, "col": node.col, "length": node.length, "filename": node.filename}


def wrap_in_cast(node: Expr, target: str) -> None:
    """Turn `node` into `Cast(target, <old node>)` in place, so every parent sees the conversion."""
    inner = copy.copy(node)
    loc = _location(node)
    node.__class__ = Cast
    node.__dict__.clear()
    node.__dict__.update(Cast(target, inner, **loc).__dict__)
    node.ty = target
    node.implicit = True  # type: ignore[attr-defined]


def wrap_in_to_string(node: Expr) -> None:
    """Turn a `str` expression into `<expr>.to_string()` in place."""
    inner = copy.copy(node)
    loc = _location(node)
    node.__class__ = MethodCall
    node.__dict__.clear()
    node.__dict__.update(MethodCall(inner, "to_string", [], **loc).__dict__)
    node.owner = "str"  # type: ignore[attr-defined]
    node.ty = "string"
    node.implicit = True  # type: ignore[attr-defined]


def as_len_field(node: MethodCall) -> None:
    """`xs.len()` on a list, array, or slice is the field `xs.len`."""
    obj = node.obj
    loc = _location(node)
    node.__class__ = FieldAccess
    node.__dict__.clear()
    node.__dict__.update(FieldAccess(obj, "len", **loc).__dict__)


def as_len_method(node: FieldAccess) -> None:
    """`s.len` on an owned `string` is the method `s.len()`."""
    obj = node.obj
    loc = _location(node)
    node.__class__ = MethodCall
    node.__dict__.clear()
    node.__dict__.update(MethodCall(obj, "len", [], **loc).__dict__)


def int_fits(ty: str, lo: int, hi: int) -> bool:
    rng = INT_RANGES.get(ty)
    return rng is not None and rng[0] <= lo and hi <= rng[1]


def zero_value(ty: str) -> str | None:
    """Source text of a neutral value of type `ty`, for a missing field."""
    from .typeinfo import FLOATS, INTS, heap_inner, heap_kind
    if ty in INTS:
        return "0"
    if ty in FLOATS:
        return "0.0"
    if ty == "bool":
        return "false"
    if ty == "str":
        return '""'
    if ty == "string":
        return "string.new()"
    if heap_kind(ty) == "List":
        return f"List[{heap_inner(ty)}]()"
    if ty.startswith("Optional["):
        return f"{ty}.None"
    return None


@lru_cache(maxsize=1)
def std_functions() -> dict[str, list[str]]:
    """Public function name -> std modules that define it (`sqrt` -> [`std.math`])."""
    from .api import library
    out: dict[str, list[str]] = {}
    try:
        symbols = library()["symbols"]
    except Exception:
        return out
    for sym in symbols:
        module = sym.get("module", "")
        if not module.startswith("std.") or sym.get("kind") not in ("function", "fn"):
            continue
        name = sym.get("name", "")
        if "." in name or not name:
            continue
        out.setdefault(name, [])
        if module not in out[name]:
            out[name].append(module)
    return out


def std_modules() -> set[str]:
    """Stems of the std modules: `math`, `string`, `fs`, ..."""
    from .api import STD
    return {p.stem for p in STD.glob("*.gg")}
