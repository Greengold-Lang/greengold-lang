"""AST nodes (dataclass based).

Each node has `line`, `col`, `length` (for error underlining).
During type checking, additional info is attached to some nodes (`ty`, `is_ref`, ...);
code generation reads only this annotated AST.
"""
from __future__ import annotations

from dataclasses import dataclass, field, fields
from typing import Optional


@dataclass(eq=False)
class Node:
    line: int = field(default=0, kw_only=True)
    col: int = field(default=0, kw_only=True)
    length: int = field(default=1, kw_only=True)
    filename: Optional[str] = field(default=None, kw_only=True)


# --- Types and parameters -------------------------------------------------

@dataclass(eq=False)
class TypeRef(Node):
    """Type name in source (`i32`, `Player`, `[N]T`, `[]T` ...)."""
    name: str
    size_expr: Optional[Expr] = field(default=None, kw_only=True)
    elem: Optional[TypeRef] = field(default=None, kw_only=True)
    is_slice: bool = field(default=False, kw_only=True)
    is_array: bool = field(default=False, kw_only=True)
    # Generic application: base="Pair", args=[i32, f64] for `Pair[i32, f64]` (name is full string).
    base: Optional[str] = field(default=None, kw_only=True)
    args: list[TypeRef] = field(default_factory=list, kw_only=True)
    # Raw pointer: `*T` (is_ptr) or `*mut T` (is_ptr + ptr_mut); pointee is in `elem`.
    is_ptr: bool = field(default=False, kw_only=True)
    ptr_mut: bool = field(default=False, kw_only=True)
    # Function pointer type `fn(A, B) -> R` (fn_ret None = no result).
    is_fn: bool = field(default=False, kw_only=True)
    fn_boxed: bool = field(default=False, kw_only=True)  # `Fn(A) -> R`: owned closure, not a bare pointer
    fn_params: list[TypeRef] = field(default_factory=list, kw_only=True)
    fn_ret: Optional[TypeRef] = field(default=None, kw_only=True)
    # Bounded int type: `int in 0..256`
    is_bounded: bool = field(default=False, kw_only=True)
    range_lo: Optional[int] = field(default=None, kw_only=True)
    range_hi: Optional[int] = field(default=None, kw_only=True)
    # `combat.Hero`: module binding, member name stays in `name` / `base`.
    qualifier: Optional[str] = field(default=None, kw_only=True)
    # `dyn Shape`: a value of any type that satisfies the feature in `base` (dynamic dispatch).
    is_dyn: bool = field(default=False, kw_only=True)


@dataclass(eq=False)
class Param(Node):
    """Function parameter.

    mode:
      ""        → value (by-value, primitive types copied; struct/heap moved)
      "consume" → owns data; dropped on scope exit
      "read"    → read-only shared reference (C: const T*)
      "lend"    → unique mutable reference (C: T*); no other read/lend at the same time
    tied_to:
      None or "self" / another param name → lifetime tie
    """
    name: str
    type_ref: TypeRef
    mode: str = ""          # "" | "consume" | "read" | "lend"
    tied_to: Optional[str] = field(default=None, kw_only=True)  # "self" or param name
    exclusive: bool = field(default=False, kw_only=True)  # `a: exclusive lend []f32`: noalias (does not overlap with other names)
    # Span of the mode keyword plus the space before the type. (0, 0, 0) when there is no keyword.
    mode_line: int = field(default=0, kw_only=True)
    mode_col: int = field(default=0, kw_only=True)
    mode_length: int = field(default=0, kw_only=True)


# --- Expressions ------------------------------------------------------------

@dataclass(eq=False)
class Expr(Node):
    # Populated by type checker.
    ty: Optional[str] = field(default=None, kw_only=True)


@dataclass(eq=False)
class IntLit(Expr):
    value: int


@dataclass(eq=False)
class FloatLit(Expr):
    text: str


@dataclass(eq=False)
class StrLit(Expr):
    value: str


@dataclass(eq=False)
class FormatStr(Expr):
    """Interpolated string: `f"Count: {x}"` -> parts: [StrLit("Count: "), Name("x")]."""
    parts: list[Expr]



@dataclass(eq=False)
class BoolLit(Expr):
    value: bool


@dataclass(eq=False)
class CharLit(Expr):
    value: int  # u8 (0..255)
    text: str = ""


@dataclass(eq=False)
class Name(Expr):
    name: str
    # Pointer in C if `read`/`consume` parameter (populated by type checker).
    is_ref: bool = field(default=False, kw_only=True)
    # Bare prelude variant like `None` (populated by type checker: enum type, variant name).
    ctor_enum: Optional[str] = field(default=None, kw_only=True)


@dataclass(eq=False)
class FieldAccess(Expr):
    obj: Expr
    field_name: str
    # Payload-less variant constructor like `Shape.Empty` (type checker writes enum type).
    ctor_enum: Optional[str] = field(default=None, kw_only=True)


@dataclass(eq=False)
class Unary(Expr):
    op: str  # "-" | "not"
    operand: Expr


@dataclass(eq=False)
class Binary(Expr):
    op: str
    left: Expr
    right: Expr


@dataclass(eq=False)
class Cast(Expr):
    target_type: str
    expr: Expr


@dataclass(eq=False)
class SoaExpr(Expr):
    """`soa Array[T, N]`: creates zeroed array of structs in SoA (separate array per field) layout."""
    type_ref: TypeRef


@dataclass(eq=False)
class CopyExpr(Expr):
    """Explicit copy: `copy x` — clones a value (without borrow checker requirements)."""
    expr: Expr


@dataclass(eq=False)
class BorrowExpr(Expr):
    """`read place` / `lend place`: borrow a place without taking ownership."""
    mode: str  # "read" | "lend"
    expr: Expr


@dataclass(eq=False)
class Call(Expr):
    callee: str
    args: list[Expr]
    # `max[i64](5, 2)` -> [i64]; otherwise empty.
    type_args: list[TypeRef] = field(default_factory=list, kw_only=True)
    # `math.max[i32](...)`: the module binding. Plain `math.sqrt(...)` stays a method call.
    qualifier: Optional[str] = field(default=None, kw_only=True)
    # Populated by type checker:
    ctor_enum: Optional[str] = field(default=None, kw_only=True)  # `Valid(x)` -> "Optional[i32]"
    inst_key: Optional[str] = field(default=None, kw_only=True)  # generic instance key "max[i64]"
    cast_to: Optional[str] = field(default=None, kw_only=True)   # `T(x)` and T numeric -> "i32"
    arg_modes: list[str] = field(default_factory=list, kw_only=True)  # for each arg: "" | "consume" | "read" | "lend"


@dataclass(eq=False)
class MethodCall(Expr):
    obj: Expr
    method: str
    args: list[Expr]
    # Populated by type checker: receiver struct name and whether method has `self: lend`.
    owner: Optional[str] = field(default=None, kw_only=True)
    self_lend: bool = field(default=False, kw_only=True)   # True: self lend/read ref (pointer in C)
    self_mode: str = field(default="", kw_only=True)       # "" | "read" | "lend"
    # Enum variant constructor like `Shape.Circle(1.0)` (type checker writes enum type).
    ctor_enum: Optional[str] = field(default=None, kw_only=True)
    arg_modes: list[str] = field(default_factory=list, kw_only=True)  # for each arg: "" | "consume" | "read" | "lend"


@dataclass(eq=False)
class Apply(Expr):
    """Call of a computed function value: `make_adder(5)(1)`, `handlers[i](3)`."""
    callee: Expr
    args: list[Expr]
    arg_modes: list[str] = field(default_factory=list, kw_only=True)


@dataclass(eq=False)
class FieldInit(Node):
    name: str
    value: Expr
    ref_mode: str = field(default="", kw_only=True)  # reference field initialization: "read" | "lend"


@dataclass(eq=False)
class StructLit(Expr):
    type_name: str
    fields: list[FieldInit]
    type_args: list[TypeRef] = field(default_factory=list, kw_only=True)
    qualifier: Optional[str] = field(default=None, kw_only=True)  # `combat.Hero { ... }`


@dataclass(eq=False)
class IndexAccess(Expr):
    obj: Expr
    index: Expr
    # In places like `Optional[i32].None`, `X[...]` can be either index or type application;
    # parser stores here if it can be read as a type, type checker decides.
    type_alt: Optional[list[TypeRef]] = field(default=None, kw_only=True)
    trusted: bool = field(default=False, kw_only=True)


@dataclass(eq=False)
class TypeApp(Expr):
    """`Pair[i32, f64]` / `Optional[[3]i32]`: bracketed name that CANNOT be an index (type application)."""
    name: str
    type_args: list[TypeRef]


@dataclass(eq=False)
class Try(Expr):
    """Postfix `?`: `f()?` (only valid as entire expression, see MatchMixin._try)."""
    operand: Expr
    # Populated by type checker: operand type (Result[T, E] | Optional[T]) and enclosing function return type.
    operand_ty: Optional[str] = field(default=None, kw_only=True)
    ret_ty: Optional[str] = field(default=None, kw_only=True)


@dataclass(eq=False)
class SliceExpr(Expr):
    obj: Expr
    start: Optional[Expr]
    end: Optional[Expr]
    inclusive: bool = False


@dataclass(eq=False)
class ArrayLit(Expr):
    elements: list[Expr]


@dataclass(eq=False)
class ArrayRepeatLit(Expr):
    value: Expr
    count: Expr


# --- Statements ------------------------------------------------------------

@dataclass(eq=False)
class Stmt(Node):
    pass


@dataclass(eq=False)
class VarDecl(Stmt):
    name: str
    mutable: bool
    type_ref: Optional[TypeRef]
    value: Expr
    ty: Optional[str] = field(default=None, kw_only=True)
    is_soa: bool = field(default=False, kw_only=True)          # `x = soa Array[T, N]`
    is_comptime_val: bool = field(default=False, kw_only=True)  # value comes from comptime fn call
    # Stored reference: "" (owns or copies the value) | "read" | "lend".
    ref_mode: str = field(default="", kw_only=True)
    # Root variable this reference is tied to (type checker).
    ref_root: Optional[str] = field(default=None, kw_only=True)


@dataclass(eq=False)
class Assign(Stmt):
    target: Expr
    op: str  # "=", "+=", "-=", "*=", "/="
    value: Expr
    # Rebind a stored reference (`r = other`, `h.field = other`) instead of writing through it.
    rebind: bool = field(default=False, kw_only=True)
    ref_mode: str = field(default="", kw_only=True)
    ref_root: Optional[str] = field(default=None, kw_only=True)


@dataclass(eq=False)
class Branch(Node):
    """`if` or `elif` branch."""
    cond: Expr
    body: list[Stmt]


@dataclass(eq=False)
class If(Stmt):
    branches: list[Branch]
    else_body: Optional[list[Stmt]]
    # `unsafe:` block: represented as single-branch If with condition `true` (every pass handles it for free).
    unsafe: bool = field(default=False, kw_only=True)


@dataclass(eq=False)
class While(Stmt):
    cond: Expr
    body: list[Stmt]


@dataclass(eq=False)
class For(Stmt):
    var: str
    start: Expr
    end: Expr
    inclusive: bool
    body: list[Stmt]
    var_ty: Optional[str] = field(default=None, kw_only=True)
    # `step K` (constant integer; negative = descending). step_value is populated by the type checker.
    step: Optional[Expr] = field(default=None, kw_only=True)
    step_value: int = field(default=1, kw_only=True)


@dataclass(eq=False)
class ForIn(Stmt):
    var: str
    iterable: Expr
    body: list[Stmt]
    elem_ty: Optional[str] = field(default=None, kw_only=True)
    mutable: bool = field(default=False, kw_only=True)            # the body changes `x`: x lends each element (inferred)
    index_var: Optional[str] = field(default=None, kw_only=True)  # `for i, x in xs`
    count: bool = field(default=False, kw_only=True)              # `for i in N` (iterable is an integer)
    by_ref: bool = field(default=False, kw_only=True)             # loop variable is a pointer to the element


@dataclass(eq=False)
class Return(Stmt):
    value: Optional[Expr]


@dataclass(eq=False)
class Break(Stmt):
    pass


@dataclass(eq=False)
class Continue(Stmt):
    pass


@dataclass(eq=False)
class Require(Stmt):
    cond: Expr


@dataclass(eq=False)
class Wrapping(Stmt):
    """Scoped wrapping arithmetic block: `wrapping: ...`"""
    body: list[Stmt]


@dataclass(eq=False)
class OverflowMode(Stmt):
    """Function/block overflow mode directive: `overflow: wrap`"""
    mode: str


@dataclass(eq=False)
class Binding(Node):
    """A name in a pattern (`Rect(w, _)` -> w and _)."""
    name: str


@dataclass(eq=False)
class RangePat(Node):
    """`lo..hi` / `lo..=hi` pattern in a scalar (integer/char) `match`."""
    lo: Expr
    hi: Expr
    inclusive: bool


@dataclass(eq=False)
class MatchArm(Node):
    """`Variant:` / `Enum.Variant(a, b):` / `_:` arm. variant=None -> `_` arm."""
    variant: Optional[str]
    qualifier: Optional[str]
    bindings: list[Binding]
    body: list[Stmt]
    has_parens: bool = False
    # Populated by type checker: variant payload types and tag order.
    payload_tys: list[str] = field(default_factory=list, kw_only=True)
    tag_index: int = field(default=-1, kw_only=True)
    # Scalar match: alternatives (`1 | 2 | 5..=9`), each a literal Expr or RangePat. Empty for enum/`_` arms.
    pats: list = field(default_factory=list, kw_only=True)
    # `pattern if cond:` runs the arm only when `cond` holds; otherwise the next arms are tried.
    guard: Optional[Expr] = field(default=None, kw_only=True)
    # `n if n > 3:`: the whole matched value under a name (only with a guard).
    whole: Optional[str] = field(default=None, kw_only=True)


@dataclass(eq=False)
class Match(Stmt):
    """`match [consume|lend] expr:` + arms."""
    scrutinee: Expr
    mode: str   # "" (read) | "consume" (payload moved) | "lend" (in-place mutation)
    arms: list[MatchArm]
    enum_ty: Optional[str] = field(default=None, kw_only=True)
    scalar_ty: Optional[str] = field(default=None, kw_only=True)  # integer / bool / u8 / str scrutinee type


@dataclass(eq=False)
class Pass(Stmt):
    """`pass`: does nothing (for empty block bodies)."""


@dataclass(eq=False)
class ExprStmt(Stmt):
    expr: Expr


@dataclass(eq=False)
class Defer(Stmt):
    """`defer call`: runs in reverse order on scope exit (including return/break/continue/`?`)."""
    stmt: Stmt


@dataclass(eq=False)
class Yield(Stmt):
    """Value of expression-style `if`/`match` arm (only found inside BlockExpr)."""
    value: Expr


@dataclass(eq=False)
class BlockExpr(Expr):
    """`if c then a else b` and `match x:` + `Arm => value` expressions.

    `stmt` is a standard If/Match statement whose arm bodies are a single `Yield`;
    this ensures type checking, exhaustiveness, and move analysis follow the exact same rules as statements.
    """
    stmt: Stmt


# --- Declarations ---------------------------------------------------------

@dataclass(eq=False)
class FieldDecl(Node):
    name: str
    type_ref: TypeRef
    mode: str = field(default="", kw_only=True)            # "" (owned field) | "read" | "lend" (reference field)
    tied_to: Optional[str] = field(default=None, kw_only=True)  # `tied to self` for reference field
    is_soa: bool = field(default=False, kw_only=True)
    is_pub: bool = field(default=False, kw_only=True)
    attrs: list = field(default_factory=list, kw_only=True)  # `@name(...)` lines above the field


@dataclass(eq=False)
class StructDecl(Node):
    name: str
    fields: list[FieldDecl]
    type_params: list[str] = field(default_factory=list, kw_only=True)
    bounds: dict = field(default_factory=dict, kw_only=True)
    is_extern: bool = field(default=False, kw_only=True)  # `extern struct`: C layout (field order / alignment identical to C)
    is_pub: bool = field(default=False, kw_only=True)
    is_union: bool = field(default=False, kw_only=True)  # `union`: the fields share one place in memory
    packed: bool = field(default=False, kw_only=True)    # `packed struct`: no padding between fields
    align: int = field(default=0, kw_only=True)          # `align(16) struct`: at least this alignment
    attrs: list = field(default_factory=list, kw_only=True)  # `@name(...)` lines above the struct


@dataclass(eq=False)
class VariantDecl(Node):
    """Enum variant: payload-less (`Empty`) or positional payload (`Circle(f32)`)."""
    name: str
    payload: list[TypeRef]
    value: Optional[int] = field(default=None, kw_only=True)  # `Red = 1`: the number `to_int` gives


@dataclass(eq=False)
class EnumDecl(Node):
    name: str
    variants: list[VariantDecl]
    type_params: list[str] = field(default_factory=list, kw_only=True)
    bounds: dict = field(default_factory=dict, kw_only=True)  # type parameter -> [feature names]
    is_pub: bool = field(default=False, kw_only=True)


@dataclass(eq=False)
class FeatureDecl(Node):
    """`feature Name:` + signatures and default method implementations. Holds FuncDecls."""
    name: str
    methods: list  # list[FuncDecl]
    is_pub: bool = field(default=False, kw_only=True)


@dataclass(eq=False)
class FuncDecl(Node):
    """Function or method. For methods, `owner` is the struct name."""
    name: str
    owner: Optional[str]
    params: list[Param]
    ret: Optional[TypeRef]
    body: list[Stmt]
    # `fn max[T](...)` -> type_params=["T"]; `fn Pair[A, B].swap(...)` -> owner_params=["A", "B"].
    type_params: list[str] = field(default_factory=list, kw_only=True)
    owner_params: list[str] = field(default_factory=list, kw_only=True)
    bounds: dict = field(default_factory=dict, kw_only=True)  # `fn f[T: Ord + Show]` -> {"T": ["Ord", "Show"]}
    # Populated by type checker for generic instantiations.
    inst_key: Optional[str] = field(default=None, kw_only=True)
    inst_note: Optional[object] = field(default=None, kw_only=True)
    from_prelude: bool = field(default=False, kw_only=True)
    # `-> ref T` / `-> lend T`: result is a pointer derived from one `read`/`lend` parameter.
    ret_view: bool = field(default=False, kw_only=True)
    ret_lend: bool = field(default=False, kw_only=True)  # `-> lend T` (mutable); otherwise `-> ref T` is shared
    ret_tied: Optional[str] = field(default=None, kw_only=True)  # `tied to param`; None = inferred from the body
    # `comptime fn`: evaluated at compile time, result embedded as constant in binary.
    is_comptime: bool = field(default=False, kw_only=True)
    overflow_mode: Optional[str] = field(default=None, kw_only=True)
    is_hot: bool = field(default=False, kw_only=True)
    attrs: list = field(default_factory=list, kw_only=True)  # `@name(...)` lines above the function
    # `test` / `test name:` lowered to a function. `gg run` does not call it.
    is_test: bool = field(default=False, kw_only=True)
    test_label: str = field(default="", kw_only=True)
    is_pub: bool = field(default=False, kw_only=True)
    # `impl combat.Hero`: the module binding. Empty when the type is in this file.
    owner_qualifier: Optional[str] = field(default=None, kw_only=True)


@dataclass(eq=False)
class ExternFuncDecl(Node):
    """C extern function declaration."""
    header: Optional[str]
    name: str
    params: list[Param]
    ret: Optional[TypeRef]
    variadic: bool = field(default=False, kw_only=True)  # `extern fn printf(fmt: *u8, ...) -> i32`
    # `weak extern`: the C function may be missing on other platforms; it is null there (call it only
    # where `target_os()` says it exists).
    weak: bool = field(default=False, kw_only=True)
    ret_ty: Optional[str] = field(default=None, kw_only=True)
    # `extern fn sqrt(...) as c_sqrt`: `name` is the Greengold name, `c_symbol` is the C name.
    c_symbol: str = field(default="", kw_only=True)
    is_pub: bool = field(default=False, kw_only=True)


@dataclass(eq=False)
class ConstDecl(Node):
    name: str
    type_ref: Optional[TypeRef]
    value: Expr
    ty: Optional[str] = field(default=None, kw_only=True)
    is_pub: bool = field(default=False, kw_only=True)
    # `static NAME: T = value`: one mutable global; reading or writing it needs `unsafe:`.
    is_static: bool = field(default=False, kw_only=True)


@dataclass(eq=False)
class AttrArg(Node):
    """One argument of `@name(...)`. `kind`: str | int | float | bool | ident. `name` is set for `key=value`."""
    kind: str
    value: object
    name: Optional[str] = field(default=None, kw_only=True)


@dataclass(eq=False)
class Attr(Node):
    """`@name` or `@name(args)` above a function, struct, or field."""
    name: str
    args: list[AttrArg] = field(default_factory=list)


@dataclass(eq=False)
class AttrParam(Node):
    name: str
    kind: str                                  # str | int | float | bool | ident
    default: Optional[AttrArg] = field(default=None, kw_only=True)


@dataclass(eq=False)
class AttrDecl(Node):
    """`attribute name(p: kind, ...) on fn, struct, field`: declares an attribute so `@name(...)` is accepted.
    `targets` empty means it may go anywhere."""
    name: str
    params: list[AttrParam] = field(default_factory=list)
    targets: list[str] = field(default_factory=list, kw_only=True)


@dataclass(eq=False)
class AllocatorDecl(Node):
    """`allocator alloc_fn, resize_fn, free_fn`: the program's heap goes through these functions."""
    alloc: str
    resize: str
    free: str


@dataclass(eq=False)
class ImportDecl(Node):
    """`import std.math`, `import std.math as m`, or `import std.math { sqrt }`."""
    path: str
    alias: Optional[str] = field(default=None, kw_only=True)
    names: list[str] = field(default_factory=list, kw_only=True)


@dataclass(eq=False)
class Program(Node):
    decls: list[Node]
    # Populated by type checker; read by code generation:
    #   type_order: struct/enum names (canonical) in registration order; *_infos: name -> info record
    #   func_instances: generic function/method instantiations (copies whose bodies passed typecheck)
    type_order: list[str] = field(default_factory=list, kw_only=True)
    struct_infos: dict = field(default_factory=dict, kw_only=True)
    enum_infos: dict = field(default_factory=dict, kw_only=True)
    func_instances: list = field(default_factory=list, kw_only=True)
    # importer slug ("" = root) -> (local name, target slug, selective names, ImportDecl)
    imports: dict = field(default_factory=dict, kw_only=True)


# --- Helpers -------------------------------------------------------------

_CHILD_FIELDS: dict[type, tuple[str, ...]] = {}


def _child_fields(cls: type) -> tuple[str, ...]:
    names = _CHILD_FIELDS.get(cls)
    if names is None:
        import dataclasses
        names = tuple(f.name for f in dataclasses.fields(cls) if f.name not in ("ty", "inst_note"))
        _CHILD_FIELDS[cls] = names
    return names


def walk(root):
    """Every node under `root` (a node or a list), parents before children, in source order.

    Only declared fields are followed (not attributes the checker adds), and `ty`/`inst_note` are skipped.
    """
    stack = [root]
    while stack:
        n = stack.pop()
        if isinstance(n, Node):
            yield n
            kids = [getattr(n, name) for name in _child_fields(type(n))]
            for k in reversed(kids):
                if isinstance(k, (Node, list)):
                    stack.append(k)
        elif isinstance(n, list):
            for x in reversed(n):
                if isinstance(x, (Node, list)):
                    stack.append(x)


def unparse(e: Expr) -> str:
    """Converts expression to source-like text (for error message hints)."""
    if isinstance(e, IntLit):
        return str(e.value)
    if isinstance(e, FloatLit):
        return e.text
    if isinstance(e, StrLit):
        return '"' + e.value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n") + '"'
    if isinstance(e, FormatStr):
        buf = []
        for p in e.parts:
            if isinstance(p, StrLit):
                buf.append(p.value.replace("{", "{{").replace("}", "}}"))
            else:
                buf.append("{" + unparse(p) + "}")
        return 'f"' + "".join(buf) + '"'
    if isinstance(e, BoolLit):
        return "true" if e.value else "false"
    if isinstance(e, CharLit):
        return f"'{e.text}'"
    if isinstance(e, Name):
        return e.name
    if isinstance(e, FieldAccess):
        return f"{unparse(e.obj)}.{e.field_name}"
    if isinstance(e, Unary):
        sep = " " if e.op == "not" else ""
        return f"{e.op}{sep}{unparse(e.operand)}"
    if isinstance(e, Binary):
        return f"{unparse(e.left)} {e.op} {unparse(e.right)}"
    if isinstance(e, Cast):
        return f"{e.target_type}({unparse(e.expr)})"
    if isinstance(e, CopyExpr):
        return f"copy {unparse(e.expr)}"
    if isinstance(e, BorrowExpr):
        return f"{e.mode} {unparse(e.expr)}"
    if isinstance(e, Call):
        targs = f"[{', '.join(t.name for t in e.type_args)}]" if e.type_args else ""
        return f"{e.callee}{targs}({', '.join(unparse(a) for a in e.args)})"
    if isinstance(e, MethodCall):
        return f"{unparse(e.obj)}.{e.method}({', '.join(unparse(a) for a in e.args)})"
    if isinstance(e, Apply):
        return f"{unparse(e.callee)}({', '.join(unparse(a) for a in e.args)})"
    if isinstance(e, StructLit):
        inner = ", ".join(f"{f.name}: {unparse(f.value)}" for f in e.fields)
        targs = f"[{', '.join(t.name for t in e.type_args)}]" if e.type_args else ""
        return f"{e.type_name}{targs}{{ {inner} }}"
    if isinstance(e, TypeApp):
        return f"{e.name}[{', '.join(t.name for t in e.type_args)}]"
    if isinstance(e, Try):
        return f"{unparse(e.operand)}?"
    if isinstance(e, IndexAccess):
        return f"{unparse(e.obj)}[{unparse(e.index)}]"
    if isinstance(e, SliceExpr):
        s = unparse(e.start) if e.start is not None else ""
        en = unparse(e.end) if e.end is not None else ""
        dot = "..=" if e.inclusive else ".."
        return f"{unparse(e.obj)}[{s}{dot}{en}]"
    if isinstance(e, ArrayLit):
        return f"[{', '.join(unparse(x) for x in e.elements)}]"
    if isinstance(e, ArrayRepeatLit):
        return f"[{unparse(e.value)}; {unparse(e.count)}]"
    if isinstance(e, BlockExpr):
        return "if ... then ... else ..." if isinstance(e.stmt, If) else "match ..."
    return "..."


_HIDDEN = {"line", "col", "length", "ty", "is_ref", "owner", "self_lend", "self_mode", "arg_modes", "var_ty", "elem_ty",
           "ctor_enum", "inst_key", "cast_to", "enum_ty", "payload_tys", "tag_index", "type_alt",
           "step_value", "by_ref", "count", "scalar_ty"}


def unparse_pat(p: object) -> str:
    """Pattern text for messages: `5`, `'a'..='z'`."""
    if isinstance(p, RangePat):
        return f"{unparse(p.lo)}{'..=' if p.inclusive else '..'}{unparse(p.hi)}"
    return unparse(p)  # type: ignore[arg-type]


def dump_ast(node: object, indent: int = 0) -> str:
    """Dumps AST as indented text (for `ast` command)."""
    pad = "  " * indent
    if isinstance(node, Node):
        lines = [f"{pad}{type(node).__name__}"]
        for f in fields(node):
            if f.name in _HIDDEN:
                continue
            lines.append(_dump_field(f.name, getattr(node, f.name), indent + 1))
        return "\n".join(lines)
    return f"{pad}{node!r}"


def _dump_field(name: str, value: object, indent: int) -> str:
    pad = "  " * indent
    if isinstance(value, Node):
        return f"{pad}{name}:\n{dump_ast(value, indent + 1)}"
    if isinstance(value, list):
        if not value:
            return f"{pad}{name}: []"
        items = "\n".join(dump_ast(v, indent + 1) for v in value)
        return f"{pad}{name}:\n{items}"
    return f"{pad}{name}: {value!r}"


def subst_self_func(decl: FuncDecl, owner: str, owner_params: list[str], qualifier: str | None = None) -> None:
    """Inside methods `Self` means the owner type (`Pair[A, B]` for generic owners).

    `qualifier` is the module in `impl shapes.Circle`, so `Self` stays `shapes.Circle`
    instead of a bare name that only exists in the other file.
    """
    import copy

    if owner_params:
        owner_args = [TypeRef(p) for p in owner_params]
        owner_tref = TypeRef(
            f"{owner}[{', '.join(owner_params)}]", base=owner, args=owner_args, qualifier=qualifier,
        )
        owner_name = f"{owner}[{', '.join(owner_params)}]"
    else:
        owner_tref = TypeRef(owner, qualifier=qualifier)
        owner_name = owner

    def fix(t: TypeRef | None) -> None:
        if t is None:
            return
        if t.name == "Self" and t.base is None and not t.args and not t.elem:
            t.__dict__.update(copy.deepcopy(owner_tref).__dict__)
            return
        fix(t.elem)
        for a in t.args:
            fix(a)
        for p in t.fn_params:
            fix(p)
        fix(t.fn_ret)
        if t.elem is not None and t.is_slice:
            t.name = f"[]{t.elem.name}"
        elif t.elem is not None and t.is_ptr:
            t.name = f"*mut {t.elem.name}" if t.ptr_mut else f"*{t.elem.name}"
        elif t.args and t.base:
            t.name = f"{t.base}[{', '.join(a.name for a in t.args)}]"

    for p in decl.params:
        fix(p.type_ref)
    fix(decl.ret)

    def walk(n: object) -> None:
        if isinstance(n, TypeRef):
            fix(n)
        elif isinstance(n, Cast):
            if n.target_type == "Self":
                n.target_type = owner_name
            walk(n.expr)
        elif isinstance(n, StructLit):
            if n.type_name == "Self":
                n.type_name = owner
                if qualifier:
                    n.qualifier = qualifier
                if owner_params and not n.type_args:
                    n.type_args = [copy.deepcopy(a) for a in owner_tref.args]
            for f in n.fields:
                walk(f)
            for ta in n.type_args:
                walk(ta)
        elif isinstance(n, TypeApp):
            if n.name == "Self":
                n.name = owner
            for a in n.type_args:
                walk(a)
        elif isinstance(n, Call):
            if n.callee == "Self":
                n.callee = owner
            for a in n.args:
                walk(a)
            for ta in n.type_args:
                walk(ta)
        elif isinstance(n, Node):
            for v in n.__dict__.values():
                if isinstance(v, (Node, list)):
                    walk(v)
        elif isinstance(n, list):
            for item in n:
                walk(item)

    walk(decl.body)

