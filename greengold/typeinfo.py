"""Common parts of type checking: constants, type-string helpers, info records.

In Greengold, a type is a STRING within the compiler ("canonical name"):
    "i32"                     primitive
    "Player"                  struct or enum
    "Pair[i32, f64]"          generic type instance (one space after comma)
    "[3]i32"  "[]i32"         array and slice
This file contains small helpers operating on those strings and dataclass types
shared between `typecheck.py` and `generics.py` / `matchcheck.py`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .ast_nodes import (
    Binary, Cast, ConstDecl, EnumDecl, Expr, ExternFuncDecl, FloatLit, FuncDecl, IntLit, Node, Param,
    StructDecl, Unary,
)

SIGNED_INTS = {"i8", "i16", "i32", "i64", "isize"}
UNSIGNED_INTS = {"u8", "u16", "u32", "u64", "usize"}
INTS = SIGNED_INTS | UNSIGNED_INTS
FLOATS = {"f32", "f64"}
NUMERIC = INTS | FLOATS
PRIMS = NUMERIC | {"bool", "str"}
TYPE_ALIASES: dict[str, str] = {
    "int": "i32",
    "uint": "u32",
    "float": "f32",
    "double": "f64",
}
BUILTIN_TYPE_ALIASES = set(TYPE_ALIASES.keys())
# FFI pointer builtins and descriptive developer-facing aliases (require `unsafe:`).
PTR_BUILTIN_ALIASES: dict[str, str] = {
    "pointer_cast": "ptr_cast",
    "pointer_offset": "ptr_offset",
    "address_of": "addr",
    "address_of_mut": "addr_mut",
    "pointer_to_int": "ptr_to_int",
    "int_to_pointer": "int_to_ptr",
}
PTR_BUILTINS = ({"addr", "addr_mut", "ptr_cast", "ptr_to_int", "int_to_ptr", "ptr_offset",
                 "cstr_to_string", "string_to_cstr", "str_from_raw", "ptr_read", "ptr_write",
                 "size_of", "align_of", "volatile_read", "volatile_write",
                 "atomic_load", "atomic_store", "atomic_add", "atomic_sub", "atomic_and", "atomic_or", "atomic_xor",
                 "atomic_swap", "atomic_cas", "fence", "asm"} | set(PTR_BUILTIN_ALIASES.keys()))
# Memory orderings of the atomic intrinsics, from weakest to strongest.
ATOMIC_ORDERS = ("relaxed", "acquire", "release", "acq_rel", "seq_cst")
# Integer intrinsics used by the Core library (checked_/saturating_/wrapping_ arithmetic).
INT_BUILTINS = {"add_overflows", "sub_overflows", "mul_overflows", "max_value", "min_value"}
BUILTINS = {"print", "eprint", "panic", "compile_error", "input", "target_os", "target_arch"} | PTR_BUILTINS | INT_BUILTINS  # builtin function names (user cannot define)
BUILTINS |= {"f32x4", "f32x8", "f64x2", "f64x4", "i32x4", "i32x8", "i64x2", "i64x4", "i16x8", "u8x16", "u32x4"}
# Names reserved by Prelude (greengold/core/core.gg): user cannot define types/functions/variables with these.
PRELUDE_NAMES = {"Optional", "Result", "Valid", "None", "Ok", "Err", "Box", "List", "Shared", "Arc", "Fn", "string"}
# Built-in owned types residing on heap: `Box[T]` and `List[T]` (see docs/DESIGN.md item 16).
HEAP_BUILTINS = {"Box", "List", "Shared", "Arc"}  # Shared: reference counted, read-only; Arc: the same, atomic
SHARED_KINDS = {"Shared", "Arc"}  # several owners, read-only `.value`
# Short constructors: `Valid(x)` == `Optional.Valid(x)` (see TypeChecker._call / _name)
SHORT_CTORS = {"Valid": "Optional", "None": "Optional", "Ok": "Result", "Err": "Result"}
VOID = "void"
ERR = "<error>"  # to suppress cascading messages after error

INT_RANGES: dict[str, tuple[int, int]] = {
    "i8": (-128, 127),
    "i16": (-32768, 32767),
    "i32": (-2147483648, 2147483647),
    "i64": (-9223372036854775808, 9223372036854775807),
    "isize": (-9223372036854775808, 9223372036854775807),
    "u8": (0, 255),
    "u16": (0, 65535),
    "u32": (0, 4294967295),
    "u64": (0, 18446744073709551615),
    "usize": (0, 18446744073709551615),
}
INT_MAX = {k: v[1] for k, v in INT_RANGES.items()}
COMPARE_OPS = {"==", "!=", "<", "<=", ">", ">="}


# -- type string helpers -----------------------------------------------------

def is_slice_type(ty: str) -> bool:
    return ty.startswith("[]")


def slice_elem_type(ty: str) -> str:
    assert is_slice_type(ty)
    return ty[2:]


def is_ptr_type(ty: str) -> bool:
    """Raw pointer: `*T` or `*mut T` (only for FFI; see docs/DESIGN.md item 15)."""
    return ty.startswith("*")


def ptr_is_mut(ty: str) -> bool:
    return ty.startswith("*mut ")


def ptr_elem(ty: str) -> str:
    """`*mut u8` -> "u8"; `*void` -> "void"."""
    assert is_ptr_type(ty)
    return ty[5:] if ty.startswith("*mut ") else ty[1:]


def make_ptr(elem: str, mut: bool = False) -> str:
    return f"*mut {elem}" if mut else f"*{elem}"


def ptr_const(ty: str) -> str:
    """`*mut T` -> `*T` (immutable view); others returned as is."""
    return "*" + ptr_elem(ty) if is_ptr_type(ty) else ty


def is_array_type(ty: str) -> bool:
    return ty.startswith("[") and not ty.startswith("[]")


def array_info(ty: str) -> tuple[int, str]:
    """`[3]i32` -> (3, "i32")."""
    assert is_array_type(ty)
    close = ty.index("]")
    return int(ty[1:close]), ty[close + 1:]


def is_bounded_int(ty: str) -> bool:
    """Returns True if `ty` is a bounded integer type, e.g. `int in 0..256` or `i64 in 0..256`."""
    if not isinstance(ty, str) or " in " not in ty or ".." not in ty:
        return False
    parts = ty.split(" in ")
    if len(parts) != 2:
        return False
    base, rng = parts
    if base != "int" and base not in INTS:
        return False
    rng_parts = rng.split("..")
    if len(rng_parts) != 2:
        return False
    try:
        int(rng_parts[0])
        int(rng_parts[1])
        return True
    except ValueError:
        return False


def bounded_int_info(ty: str) -> tuple[str, int, int]:
    """Returns (base_type, lo, hi) for bounded integer type. E.g. 'int in 0..256' -> ('i64', 0, 256)."""
    assert is_bounded_int(ty), f"not a bounded int type: {ty}"
    base, rng = ty.split(" in ")
    lo_str, hi_str = rng.split("..")
    base_ty = "i64" if base == "int" else base
    return base_ty, int(lo_str), int(hi_str)


def int_base(ty: str) -> str:
    """Strips a range bound: `u32 in 0..16` -> `u32`; any other type is returned as is."""
    return bounded_int_info(ty)[0] if is_bounded_int(ty) else ty


def make_bounded_int(base: str, lo: int, hi: int) -> str:
    """Constructs canonical bounded integer type string."""
    return f"{base} in {lo}..{hi}"


def is_fn_type(ty: str) -> bool:
    """Function pointer type: `fn(i32,i32)->i32` (return `void` when none)."""
    return ty.startswith("fn(")


def is_boxed_fn(ty: str) -> bool:
    """Owned closure type: `Fn(i32)->i32` (code + reference-counted environment)."""
    return isinstance(ty, str) and ty.startswith("Fn(")


def make_fn(params: list[str], ret: str) -> str:
    return f"fn({','.join(params)})->{ret}"


def make_boxed_fn(params: list[str], ret: str) -> str:
    return f"Fn({','.join(params)})->{ret}"


def fn_parts(ty: str) -> tuple[list[str], str]:
    """`fn(i32,List[i32])->bool` (or `Fn(...)`) -> (["i32", "List[i32]"], "bool")."""
    assert is_fn_type(ty) or is_boxed_fn(ty)
    depth, close = 0, -1
    for i in range(2, len(ty)):
        c = ty[i]
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                close = i
                break
    inner = ty[3:close]
    params: list[str] = []
    depth, start = 0, 0
    for i, ch in enumerate(inner):
        if ch in "([":
            depth += 1
        elif ch in ")]":
            depth -= 1
        elif ch == "," and depth == 0:
            params.append(inner[start:i])
            start = i + 1
    if inner:
        params.append(inner[start:])
    return params, ty[close + 3:]


def generic_parts(ty: str) -> tuple[str, list[str]] | None:
    """`Pair[i32, f64]` -> ("Pair", ["i32", "f64"]); None if not a generic instance."""
    if ty.startswith(("[", "*", "fn(", "Fn(")) or "[" not in ty or not ty.endswith("]"):
        return None
    i = ty.index("[")
    inner = ty[i + 1:-1]
    args: list[str] = []
    depth, start = 0, 0
    for pos, ch in enumerate(inner):
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
        elif ch == "," and depth == 0:
            args.append(inner[start:pos].strip())
            start = pos + 1
    args.append(inner[start:].strip())
    return ty[:i], args


def is_dyn_type(ty: object) -> bool:
    """`dyn Shape` (canonical: `dyn ` + the feature key): an owned value of any type with that feature."""
    return isinstance(ty, str) and ty.startswith("dyn ")


def dyn_feature(ty: str) -> str:
    return ty[len("dyn "):]


def heap_kind(ty: str) -> str | None:
    """`Box[T]` -> "Box", `List[T]` -> "List"; None for any other type."""
    parts = generic_parts(ty)
    return parts[0] if parts is not None and parts[0] in HEAP_BUILTINS else None


def heap_inner(ty: str) -> str:
    """`List[i32]` -> "i32"."""
    parts = generic_parts(ty)
    assert parts is not None and parts[0] in HEAP_BUILTINS
    return parts[1][0]


def needs_drop(ty: str, structs: dict, enums: dict, _seen: frozenset[str] = frozenset()) -> bool:
    """Does type contain owned heap memory (requires `drop` at scope end)? These types cannot be copied, only moved."""
    if ty in _seen or ty in PRIMS:
        return False
    if heap_kind(ty) is not None or is_boxed_fn(ty) or is_dyn_type(ty):
        return True
    seen = _seen | {ty}
    if is_array_type(ty):
        return needs_drop(array_info(ty)[1], structs, enums, seen)
    if is_slice_type(ty):
        return False  # slices are view only
    if ty in structs:
        si = structs[ty]
        if si.user_drop:
            return True
        return any(needs_drop(t, structs, enums, seen) for n, t in si.fields.items() if n not in si.field_modes)
    if ty in enums:
        if enums[ty].user_drop:
            return True
        return any(needs_drop(t, structs, enums, seen) for v in enums[ty].variants.values() for t in v.payload)
    return False


# OS handles of `std.thread`. Their bytes are the OS object, so a copy would be a second, unrelated
# object: `n = m` would be a new lock and a copied channel an empty queue. They are moved, never copied.
HANDLE_STRUCTS = {"Thread", "Mutex", "Cond", "AtomicI64", "Channel", "Queue", "Atomic", "Locked"}
_STD_THREAD = (Path(__file__).parent / "std" / "thread.gg").resolve()


def is_handle_decl(decl: StructDecl) -> bool:
    filename = getattr(decl, "filename", None)
    if not filename or decl.name not in HANDLE_STRUCTS:
        return False
    try:
        return Path(filename).resolve() == _STD_THREAD
    except OSError:
        return False


def held_handle(ty: str, structs: dict, enums: dict, _seen: frozenset[str] = frozenset()) -> str | None:
    """The OS handle type held by value inside `ty` (`ty` itself, a field, an element), or None."""
    if ty in _seen or ty in PRIMS:
        return None
    seen = _seen | {ty}
    if is_array_type(ty):
        return held_handle(array_info(ty)[1], structs, enums, seen)
    if heap_kind(ty) is not None:
        return held_handle(heap_inner(ty), structs, enums, seen)
    if ty in structs:
        si = structs[ty]
        if si.handle:
            return ty
        for n, t in si.fields.items():
            if n not in si.field_modes:
                found = held_handle(t, structs, enums, seen)
                if found is not None:
                    return found
        return None
    if ty in enums:
        for v in enums[ty].variants.values():
            for t in v.payload:
                found = held_handle(t, structs, enums, seen)
                if found is not None:
                    return found
    return None


def thread_problem(ty: str, structs: dict, enums: dict, _seen: frozenset[str] = frozenset()) -> str | None:
    """Why a value of `ty` cannot go to another thread, or None when it can.

    This is the compiler's Send/Share rule. It is inferred from the type and never written: a value may
    cross threads when nothing in it is a view of memory another thread could free (`str`, slices,
    reference fields), a raw pointer, or an owner count that is not atomic (`Shared`, `Fn`). `Arc[T]`
    crosses threads when `T` does, because every owner then reads the same `T` at once.
    """
    if ty in _seen:
        return None
    if ty == "str":
        return "`str` is a view into memory that another thread could free; send a `string` (`.to_string()`)"
    if ty in PRIMS or is_fn_type(ty):
        return None
    if is_slice_type(ty):
        return f"`{ty}` is a view into memory that another thread could free"
    if is_ptr_type(ty):
        return f"`{ty}` is a raw pointer; the compiler cannot see who else uses that memory"
    if is_dyn_type(ty):
        return f"a `{ty.replace('::', '.')}` value may hold a value of any type"
    if is_boxed_fn(ty):
        return (f"a stored `{ty.replace('->void', '')}` value may hold any captures and counts its owners without atomics; "
                "write the lambda itself at the call")
    seen = _seen | {ty}
    hk = heap_kind(ty)
    if hk == "Shared":
        return f"`{ty}` counts its owners without atomics; use `Arc[{heap_inner(ty)}]`"
    if hk is not None:
        return thread_problem(heap_inner(ty), structs, enums, seen)
    if is_array_type(ty):
        return thread_problem(array_info(ty)[1], structs, enums, seen)
    if ty in structs:
        si = structs[ty]
        if si.handle:  # `std.thread` synchronizes these itself; only what they carry matters
            parts = generic_parts(ty)
            for arg in (parts[1] if parts else []):
                found = thread_problem(arg, structs, enums, seen)
                if found:
                    return found
            return None
        for name, fty in si.fields.items():
            if name in si.field_modes:
                return f"`{ty}` holds the reference field `{name}`"
            found = thread_problem(fty, structs, enums, seen)
            if found:
                return found
        return None
    if ty in enums:
        for v in enums[ty].variants.values():
            for pt in v.payload:
                found = thread_problem(pt, structs, enums, seen)
                if found:
                    return found
    return None


def moves(ty: str, structs: dict, enums: dict) -> bool:
    """Is a value of `ty` moved instead of copied? Heap owners (see `needs_drop`) and OS handles."""
    return needs_drop(ty, structs, enums) or held_handle(ty, structs, enums) is not None


def is_const_arg(ty: str) -> bool:
    """Is a generic argument the value of a constant parameter (`3` in `Grid[3]`) rather than a type?"""
    return ty.lstrip("-").isdigit()


def make_generic(base: str, args: list[str]) -> str:
    """("Pair", ["i32", "f64"]) -> `Pair[i32, f64]`."""
    return f"{base}[{', '.join(args)}]"


def canonical_type(ty: str) -> str:
    """Canonicalize type string, replacing aliases like int -> i32, []float -> []f32, etc."""
    if not ty:
        return ty
    if ty in TYPE_ALIASES:
        return TYPE_ALIASES[ty]
    if is_slice_type(ty):
        return f"[]{canonical_type(slice_elem_type(ty))}"
    if is_ptr_type(ty):
        mut = ptr_is_mut(ty)
        elem = canonical_type(ptr_elem(ty))
        return make_ptr(elem, mut)
    if is_array_type(ty):
        count, elem = array_info(ty)
        return f"[{count}]{canonical_type(elem)}"
    if is_fn_type(ty):
        params, ret = fn_parts(ty)
        c_params = [canonical_type(p) for p in params]
        c_ret = canonical_type(ret)
        return make_fn(c_params, c_ret)
    parts = generic_parts(ty)
    if parts is not None:
        base, args = parts
        c_base = TYPE_ALIASES.get(base, base)
        c_args = [canonical_type(a) for a in args]
        return make_generic(c_base, c_args)
    return ty


def mangle(ty: str) -> str:
    """Mangles type string to C identifier: `Optional[Pair[i32, f64]]` -> `Optional_Pair_i32_f64`."""
    if "::" in ty:
        ty = ty.replace("::", "_")
    if is_fn_type(ty):
        ps, r = fn_parts(ty)
        return "FN_" + "_".join(mangle(p) for p in ps) + "_R_" + mangle(r)
    if is_ptr_type(ty):
        return ("PM_" if ptr_is_mut(ty) else "P_") + mangle(ptr_elem(ty))
    if is_slice_type(ty):
        return "S_" + mangle(slice_elem_type(ty))
    if is_array_type(ty):
        n, elem = array_info(ty)
        return f"A{n}_" + mangle(elem)
    parts = generic_parts(ty)
    if parts is not None:
        return "_".join([parts[0]] + [mangle(a) for a in parts[1]])
    return ty


def func_cname(key: str) -> str:
    """Mangles function key to C identifier.

    `Optional[i32].assume_valid` -> `Optional_i32_assume_valid`.
    `math::sqrt` -> `math_sqrt`. `combat::Player.heal` -> `combat_Player_heal`.
    """
    mod = ""
    if "::" in key:
        mod, key = key.split("::", 1)
    if "." in key:
        owner, method = key.rsplit(".", 1)
        base = f"{mangle(owner)}_{method}"
    else:
        base = mangle(key)
    return f"{mod}_{base}" if mod else base


def is_const_expr(e: Expr) -> bool:
    """Is expression composed solely of numeric constants? (for literal type coercion / inference)"""
    if isinstance(e, (IntLit, FloatLit)):
        return True
    if isinstance(e, Unary) and e.op in ("-", "~"):
        return is_const_expr(e.operand)
    if isinstance(e, Binary) and e.op in ("+", "-", "*", "/", "%", "&", "|", "^", "<<", ">>"):
        return is_const_expr(e.left) and is_const_expr(e.right)
    if isinstance(e, Cast):
        return is_const_expr(e.expr)
    return False


# -- records -----------------------------------------------------------------

@dataclass
class StructInfo:
    name: str  # canonical name (`Pair[i32, f64]` for generic instance)
    fields: dict[str, str]
    decl: StructDecl
    # Reference fields (`owner: read Player tied to self`): field name -> "read" | "lend"; do not carry ownership.
    field_modes: dict[str, str] = field(default_factory=dict)
    field_tied: dict[str, str] = field(default_factory=dict)
    field_pub: dict[str, bool] = field(default_factory=dict)
    handle: bool = False  # an OS handle of `std.thread` (see `HANDLE_STRUCTS`): moved, never copied
    user_drop: bool = False  # `impl T: fn drop(self: lend Self)`: moved, and `drop` runs before the fields are freed


@dataclass
class VariantInfo:
    name: str
    payload: list[str]  # payload types (positional)
    index: int  # variant order = tag value


@dataclass
class EnumInfo:
    name: str  # canonical name
    variants: dict[str, VariantInfo]
    decl: EnumDecl
    user_drop: bool = False  # see `StructInfo.user_drop`


@dataclass
class ConstInfo:
    name: str
    ty: str
    eval_val: int | float | None
    decl: ConstDecl


@dataclass
class ParamInfo:
    name: str
    ty: str
    mode: str
    node: Param | None
    # Written with type parameter in generic function (e.g. `x: consume T`): `consume` is not an error on copyable type.
    generic: bool = False


@dataclass
class FuncInfo:
    key: str  # "add", "Player.take_damage", "max[i64]", "Optional[i32].assume_valid"
    params: list[ParamInfo]  # in methods first element is `self`
    ret: str
    owner: str | None
    decl: FuncDecl | ExternFuncDecl
    is_extern: bool = False
    header: str | None = None
    # In generic instantiations: type parameter -> concrete type (empty for non-templates)
    bindings: dict[str, str] = field(default_factory=dict)
    is_instance: bool = False
    depth: int = 0  # instantiation depth (for infinite recursive instantiation check)
    ret_view: bool = False  # `-> ref T` / `-> lend T`: return is a pointer, not an owned value
    ret_lend: bool = False  # `-> lend T`
    ret_origin: str | None = None  # parameter the returned reference is tied to


@dataclass
class VarInfo:
    name: str
    ty: str
    mutable: bool
    kind: str  # "local" | "val" | "consume" | "read" | "lend" | "loop" | "const"
    # `match lend s` bindings are aliases to a path inside s (for alias checking).
    alias: tuple[str, ...] | None = None
    # `for x in xs` element reference (read-only unless the body changes it).
    loop_ref: bool = False
    # Local that stores a reference (`r: read T = ...`). The slot is `T*`, not `T`.
    ref_slot: bool = False
    # Ultimate referent root (variable name) this reference is tied to.
    tie: str | None = None
    # Declaration this binding came from (Param or VarDecl).
    origin: Node | None = None
    # Counter of `for i in 0..10` with constant bounds: every value lies in [lo, hi], so it converts to any
    # integer type that holds that range.
    lit_range: tuple[int, int] | None = None


@dataclass
class ArgAccess:
    mode: str  # "lend" | "consume" | "read" | "val"
    path: tuple[str, ...] | None
    ty: str
    target: Expr
    node: Node
    is_receiver: bool = False
