"""Type checking and move analysis.

There are two separate classes:
  * `TypeChecker`  : symbol table, type inference, ownership mode (`consume`/`read`/`lend`) rules.
  * `MoveAnalyzer` : catches use-after-move of moved (`consume`) variables.
                     Runs if type checking succeeds without errors.

Type checking decorates the AST (`ty`, `is_ref`, `owner`, `self_lend`, `arg_modes` ...); codegen reads these.
"""
from __future__ import annotations

import copy
import difflib
import pickle
import re
from dataclasses import dataclass, replace as dc_replace
from pathlib import Path

from .ast_nodes import (
    Apply,
    ArrayLit, ArrayRepeatLit, Assign, Binary, BoolLit, Break, Call, Cast, EnumDecl, Match,
    CharLit, ConstDecl, Continue, Expr, ExprStmt, ExternFuncDecl, FieldAccess, FloatLit, For, ForIn,
    FuncDecl, If, IndexAccess, IntLit, MethodCall, CopyExpr, BorrowExpr, SoaExpr, Name, Node, Param, Pass,
    Program, Return, SliceExpr, Stmt, StrLit, StructDecl, StructLit, TypeApp, TypeRef,
    Try, Unary, VarDecl, While, Yield, BlockExpr, Defer, unparse, subst_self_func, FormatStr,
    Require, Wrapping, OverflowMode,
)
from .diagnostics import DiagnosticBag, Edit, Fix, Label, Note
from .closures import ClosureMixin, _at, _replace
from . import friendly
from .attrs import check_attributes, run_handlers as run_attribute_handlers
from .generics import GenericsMixin
from .lexer import tokenize
from .matchcheck import MatchMixin
from .parser import parse
from .simd import SIMD_TYPES, SimdCheckMixin, is_simd
from .typeinfo import (
    TYPE_ALIASES, BUILTIN_TYPE_ALIASES, canonical_type,  # noqa: F401  (other modules import these names from here as well)
    ArgAccess, BUILTINS, COMPARE_OPS, ConstInfo, EnumInfo, ERR, FLOATS, FuncInfo, INT_MAX,
    INT_RANGES, INTS, NUMERIC, PRELUDE_NAMES, PRIMS, ParamInfo, SHORT_CTORS, SIGNED_INTS, StructInfo,
    UNSIGNED_INTS, VOID, VarInfo, VariantInfo, array_info, func_cname, generic_parts, is_array_type,
    is_const_expr, is_slice_type, make_generic, slice_elem_type,
    HEAP_BUILTINS, SHARED_KINDS, heap_inner, heap_kind, thread_problem, is_dyn_type, dyn_feature, needs_drop, held_handle, is_handle_decl, moves,
    PTR_BUILTINS, PTR_BUILTIN_ALIASES, is_ptr_type, make_ptr, ptr_const, ptr_elem, ptr_is_mut,
    fn_parts, is_fn_type, make_fn, INT_BUILTINS, is_boxed_fn, make_boxed_fn,
    is_bounded_int, bounded_int_info, make_bounded_int, int_base, is_const_arg,
)


# `{x:spec}` in an f-string: [[fill]align][+][#][0][width][.precision][type]
FORMAT_SPEC = re.compile(r"^(?:(?P<fill>.)?(?P<align>[<>^]))?(?P<sign>\+)?(?P<alt>#)?(?P<zero>0)?"
                         r"(?P<width>\d+)?(?:\.(?P<prec>\d+))?(?P<kind>[xXbodeE])?$")

# List methods written in Greengold (core.gg `_list_<name>`); the compiler rewrites `xs.name(...)` into a call.
LIST_HELPERS = {"map", "filter", "fold", "any", "all", "count", "find", "position", "index_of", "contains",
                "sum", "min", "max", "first", "last", "is_empty", "reverse", "extend", "sort", "sort_by", "join"}
LIST_ANY_ELEM = {"is_empty", "reverse", "join"}  # the rest copy elements out of the list
# Which argument is a callback, and which of its parameters receive an element.
LIST_CALLBACK_SLOT = {m: (0, (0,)) for m in ("map", "filter", "any", "all", "count", "find", "position")}
LIST_CALLBACK_SLOT.update(fold=(1, (1,)), sort_by=(0, (0, 1)))
LIST_HELPER_ARGS = {m: 1 for m in (*LIST_CALLBACK_SLOT, "contains", "index_of", "extend", "join")} | {"fold": 2}


def prelude_path() -> Path:
    """Absolute path of the Core library source (`greengold/core/core.gg`)."""
    return (Path(__file__).parent / "core" / "core.gg").resolve()


def is_prelude_file(filename: str) -> bool:
    """True when `filename` is the Core library itself, not a user program that uses it."""
    if not filename or filename == "<source>":
        return False
    try:
        return Path(filename).resolve() == prelude_path()
    except OSError:
        return False


_PRELUDE_CACHE: dict[str, tuple[float, bytes]] = {}


def load_prelude() -> list[Node]:
    """Parses `greengold/core/core.gg` (Core library); marks declarations as `from_prelude=True`.
    The parse is kept as a pickle per process: each check gets fresh nodes without lexing the file again."""
    path = prelude_path()
    stamp = path.stat().st_mtime
    cached = _PRELUDE_CACHE.get(str(path))
    if cached is not None and cached[0] == stamp:
        return pickle.loads(cached[1])
    text = path.read_text(encoding="utf-8")
    diags = DiagnosticBag()
    program = parse(tokenize(text, diags), diags)
    if diags.has_errors():  # compiler internal error
        raise RuntimeError("failed to parse core.gg: " + "; ".join(d.message for d in diags.items))
    for d in program.decls:
        d.from_prelude = True  # type: ignore[attr-defined]
    decls = list(program.decls)
    _PRELUDE_CACHE[str(path)] = (stamp, pickle.dumps(decls, protocol=pickle.HIGHEST_PROTOCOL))
    return decls


def _place_path(e: Expr) -> tuple[str, ...] | None:
    """`a.b.c` -> ("a","b","c"); `a[i]` -> ("a",); None if not addressable."""
    if isinstance(e, BorrowExpr):
        return _place_path(e.expr)
    if isinstance(e, Name):
        return (e.name,)
    if isinstance(e, FieldAccess):
        base = _place_path(e.obj)
        return None if base is None else base + (e.field_name,)
    if hasattr(e, "obj") and type(e).__name__ in ("IndexAccess", "SliceExpr"):
        return _place_path(getattr(e, "obj"))
    return None


def _overlap(a: tuple[str, ...], b: tuple[str, ...]) -> bool:
    n = min(len(a), len(b))
    return a[:n] == b[:n]


_is_const_expr = is_const_expr  # backwards compatible alias


def is_panic_stmt(s: Stmt) -> bool:
    """Is this a `panic("...")` statement? It is terminating: treated like `return`."""
    return isinstance(s, ExprStmt) and isinstance(s.expr, Call) and s.expr.callee == "panic"


def _always_returns(stmts: list[Stmt]) -> bool:
    """Does block end with `return`/`panic` on all paths? (while/for excluded: conservative)"""
    for s in stmts:
        if isinstance(s, Return) or is_panic_stmt(s):
            return True
        if isinstance(s, If) and s.unsafe and _always_returns(s.branches[0].body):
            return True
        if isinstance(s, If) and s.else_body is not None:
            if all(_always_returns(b.body) for b in s.branches) and _always_returns(s.else_body):
                return True
        # `match` is exhaustive (checked at compile time): if all arms terminate, match terminates too.
        if isinstance(s, Match) and s.arms and all(_always_returns(a.body) for a in s.arms):
            return True
    return False


class TypeChecker(ClosureMixin, MatchMixin, GenericsMixin, SimdCheckMixin):
    def __init__(self, program: Program, diags: DiagnosticBag, filename: str = "<source>",
                 require_main: bool = True, inferred: dict[tuple, str] | None = None) -> None:
        self.program = program
        self.diags = diags
        self.filename = filename  # for instantiation notes like "call: a.gg:12:5"
        self.require_main = require_main
        self.mode_upgrades: dict[tuple, str] = {}  # inferred parameter -> "lend" | "consume" (see check_program)
        # (file, line, col, name) of each checked `x = ...` -> was it ever changed? Unchanged ones are `fixed`.
        self.var_changes: dict[tuple, bool] = {}
        self.inferred: dict[tuple, str] = dict(inferred or {})  # parameter / capture modes from earlier passes
        # `x = None` with no type: the first `x = Valid(v)` (or a use where an `Optional[T]` is expected) gives
        # the type; check_program then re-checks with it (key from `_none_key`, stored in `inferred`).
        self.none_pending: dict[tuple, VarDecl] = {}
        self.none_found: dict[tuple, str] = {}
        self._init_closures({(k[1], k[2]): m for k, m in self.inferred.items() if k[0] == "capture"})
        # Prelude (Optional/Result) comes BEFORE user declarations; `program.decls` is unchanged.
        # The Core file is the prelude: prepending it again would report every name as a duplicate.
        if is_prelude_file(filename):
            for d in program.decls:
                d.from_prelude = True  # type: ignore[attr-defined]
            self.decls: list[Node] = list(program.decls)
        else:
            self.decls = load_prelude() + list(program.decls)
        self.structs: dict[str, StructInfo] = {}
        self.enums: dict[str, EnumInfo] = {}
        self.type_order: list[str] = []  # struct/enum names in registration order (for codegen)
        # Generic templates (bodies checked at instantiation time, see generics.py)
        self.generic_structs: dict[str, StructDecl] = {}
        self.generic_enums: dict[str, EnumDecl] = {}
        self.generic_funcs: dict[str, FuncDecl] = {}
        self.method_templates: dict[str, FuncDecl] = {}  # "Pair.swap" -> template
        self.drop_owners: set[str] = set()  # canonical type keys with `fn drop(self: lend Self)`
        self.tparams: dict[str, str] = {}  # active type parameter bindings (T -> i32)
        self.pending: list[FuncInfo] = []  # functions awaiting body checking
        self.const_types: dict[str, str] = {}  # constant parameter -> its integer type, in the current instance
        self.instances: list[FuncDecl] = []  # generated function instances (for codegen)
        self.instance_cnames: list[tuple[str, str, Node]] = []  # (C name, source, location)
        self.depth = 0  # instantiation depth
        self.try_allowed: Expr | None = None  # only expr where `?` is allowed (see MatchMixin._try)
        self._reported: set[tuple[int, int, str]] = set()  # report same error at same location only once
        self.consts: dict[str, ConstInfo] = {}
        self.funcs: dict[str, FuncInfo] = {}
        self.free_funcs: set[str] = set()
        self.scopes: list[dict[str, VarInfo]] = []
        self.cur: FuncInfo | None = None
        self.loop_depth = 0
        self.features: dict = {}
        self.yields: list[dict] = []  # type frames for nested if/match expressions
        self.unsafe_depth = 0  # current depth of nested `unsafe:` blocks
        self.scope_slug = ""  # "" is the program root; imported files use their slug
        self.mod_binds: dict[str, dict[str, str]] = {}
        self.selective: dict[str, dict[str, str]] = {}
        self._selective_raw: dict[str, dict[str, tuple[str, str, Node]]] = {}

    # -- helpers -------------------------------------------------
    def _drop(self, ty: str) -> bool:
        """Does `ty` contain heap-owned memory? (cannot be copied, only moved, dropped at scope end)"""
        return ty != ERR and needs_drop(ty, self.structs, self.enums)

    def _moves(self, ty: str) -> bool:
        """Is `ty` moved instead of copied? Heap owners and the OS handles of `std.thread`."""
        return ty != ERR and moves(ty, self.structs, self.enums)

    @staticmethod
    def _is_place_expr(e: Expr) -> bool:
        """Is it a place (variable, field, index, slice)? Calls, literals, bare variant constructors are fresh values."""
        if getattr(e, "is_view", False):
            return True  # `ref` return is also a place: unowned view
        return isinstance(e, (Name, FieldAccess, IndexAccess, SliceExpr)) and getattr(e, "ctor_enum", None) is None

    def _no_implicit_copy(self, e: Expr, ty: str) -> None:
        """Storing a heap-owning value elsewhere as a NEW owner: if source is a place (`x`, `p.field`),
        ownership is MOVED (implicit move; marked `is_move`). Fresh values (calls, constructors) are free."""
        if not self._moves(ty):
            return
        if getattr(e, "is_view", False):
            self._err(e, f"`{unparse(e)}` is a view (`ref`); heap-owning `{ty}` cannot be copied.",
                      "Views are read-only (field access, `match`, `read` parameter).")
        elif isinstance(e, (Name, FieldAccess, IndexAccess)) and getattr(e, "ctor_enum", None) is None:
            if self._check_move(e, e):
                e.is_move = True

    def _err(self, node: Node, msg: str, hint: str | None = None, notes: list[Note] | None = None, *,
             rule: str | None = None, labels: list[Label] | None = None,
             details: dict | None = None, fixes: list[Fix] | None = None) -> None:
        node_file = getattr(node, "filename", None) or self.filename
        key = (node_file, node.line, node.col, msg)
        if key in self._reported:  # do not re-report the same error across multiple instantiations
            return
        self._reported.add(key)
        if self.cur is not None and self.cur.is_instance:
            note = getattr(self.cur.decl, "inst_note", None)
            if note is not None:
                notes = (notes or []) + [note]
        self.diags.error(msg, node.line, node.col, node.length, hint, notes, filename=node_file,
                         rule=rule, labels=labels, details=details, fixes=fixes)

    def _def_label(self, var: VarInfo | None, text: str) -> list[Label]:
        node = getattr(var, "origin", None) if var is not None else None
        if node is None:
            return []
        return [Label("definition", text, node.line, node.col, max(node.length, 1),
                      getattr(node, "filename", None))]

    def _place_fixes(self, root: VarInfo, what: str) -> list[Fix]:
        """Mechanical edit when the author almost certainly wanted this place to be mutable."""
        origin = root.origin
        fixed_at = getattr(origin, "fixed_at", None)
        if isinstance(origin, VarDecl) and not origin.mutable and fixed_at is not None:
            line, col = fixed_at
            return [Fix(
                f"Delete `fixed` so `{root.name}` can be changed",
                "likely",
                [Edit(line, col, line, col + len("fixed "), "", getattr(origin, "filename", None))],
            )]
        if isinstance(origin, Param) and what in ("assign", "lend", "method"):
            if origin.mode == "" and origin.type_ref is not None:
                return [Fix(
                    f"Lend `{origin.name}` so the function can change it (`{origin.name}: lend ...`)",
                    "likely",
                    [Edit(origin.type_ref.line, origin.type_ref.col, origin.type_ref.line, origin.type_ref.col,
                          "lend ", getattr(origin, "filename", None))],
                )]
            if origin.mode == "read" and origin.mode_length:
                word = "lend" + (" " if origin.mode_length > len("read") else "")
                return [Fix(
                    f"Change `{origin.name}` from `read` to `lend`",
                    "likely",
                    [Edit(origin.mode_line, origin.mode_col, origin.mode_line, origin.mode_col + origin.mode_length,
                          word, getattr(origin, "filename", None))],
                )]
        return []

    def _lookup(self, name: str) -> VarInfo | None:
        for scope in reversed(self.scopes):
            if name in scope:
                return scope[name]
        key = self._resolve_simple(name)
        if key is not None and key in self.consts and self._is_visible(self.consts[key].decl):
            info = self.consts[key]
            if getattr(info.decl, "is_static", False):
                return VarInfo(name, info.ty, True, "static", origin=info.decl)
            return VarInfo(name, info.ty, False, "const", origin=info.decl)
        return None

    def _init_modules(self) -> None:
        """Import bindings are per file. Selective names are checked after symbols exist."""
        self.mod_binds = {}
        self.selective = {}
        self._selective_raw = {}
        raw = getattr(self.program, "imports", None) or {}
        for importer, binds in raw.items():
            mods: dict[str, str] = {}
            sels: dict[str, tuple[str, str, Node]] = {}
            for local, target, names, decl in binds:
                if names:
                    sels[local] = (target, names[0], decl)
                else:
                    mods[local] = target
            self.mod_binds[importer] = mods
            self._selective_raw[importer] = sels

    def _enter(self, decl: Node) -> None:
        if getattr(decl, "from_prelude", False):
            self.scope_slug = ""
        else:
            self.scope_slug = getattr(decl, "module_slug", "") or ""

    def _sym_key(self, decl: Node, name: str) -> str:
        if getattr(decl, "from_prelude", False):
            return name
        slug = getattr(decl, "module_slug", "") or ""
        return f"{slug}::{name}" if slug else name

    def _decl_for(self, key: str) -> Node | None:
        for table in (self.structs, self.enums, self.consts, self.funcs):
            info = table.get(key)
            if info is not None:
                return info.decl
        features = getattr(self, "features", None) or {}
        for table in (self.generic_structs, self.generic_enums, self.generic_funcs, features):
            found = table.get(key)
            if found is not None:
                return found
        return None

    def _has_any(self, key: str) -> bool:
        return self._decl_for(key) is not None

    def _is_visible(self, decl: Node) -> bool:
        """Own module sees private names. Other modules see names under `public`. Prelude is always visible."""
        if getattr(decl, "from_prelude", False):
            return True
        slug = getattr(decl, "module_slug", "") or ""
        if slug == self.scope_slug:
            return True
        return bool(slug) and bool(getattr(decl, "is_pub", False))

    @staticmethod
    def _through_shared(place: Expr) -> str | None:
        """`s` when `place` is `s.value` (or inside it) of a `Shared[T]`."""
        e = place
        while isinstance(e, (FieldAccess, IndexAccess, SliceExpr)):
            if isinstance(e, FieldAccess) and e.field_name == "value" and \
                    heap_kind(getattr(e.obj, "ty", None) or "") in SHARED_KINDS:
                return unparse(e.obj)
            e = e.obj
        return None

    def _is_type_arg(self, ty: str) -> bool:
        """True inside a generic instance when `ty` was passed in as a type argument: the generic code may
        call that type's methods (`hash`, `eq`, ...) even when they are private to the caller's module."""
        return self.cur is not None and self.cur.is_instance and ty in self.cur.bindings.values()

    def _is_type_name(self, name: str) -> bool:
        """True when `name` is a type here, including a prelude type that shares a module's name."""
        key = self._resolve_simple(name) or name
        return (key in self.structs or key in self.enums or key in self.generic_structs
                or key in self.generic_enums or name in PRIMS)

    def _resolve_simple(self, name: str) -> str | None:
        """Source name → canonical key (`combat::Hero` or bare `Hero` for the root and prelude)."""
        slug = self.scope_slug
        if slug:
            local = f"{slug}::{name}"
            if self._has_any(local):
                return local
        picked = self.selective.get(slug, {}).get(name)
        if picked is not None:
            return picked
        if self._has_any(name) and (slug == "" or getattr(self._decl_for(name), "from_prelude", False)):
            return name
        return None

    def _qualified_item(self, module: str, item: str, node: Node, missing_ok: bool = False) -> str | None | bool:
        """None if `module` is not an import. False if the lookup failed. Otherwise the canonical key.

        `missing_ok`: a missing item returns None, so a prelude type of the same name (`string.new`) can be tried.
        """
        slug = self.mod_binds.get(self.scope_slug, {}).get(module)
        if slug is None:
            return None
        key = f"{slug}::{item}"
        decl = self._decl_for(key)
        if decl is None:
            if missing_ok:
                return None
            self._err(node, f"Module `{module}` has no `{item}`.",
                      "Only names defined in that file can be used.")
            return False
        if not getattr(decl, "is_pub", False):
            self._err(node, f"`{item}` is private in module `{module}`.",
                      f"Put `{item}` under a `public` line in that module.")
            return False
        return key

    def _finish_selective(self, quiet: bool = False) -> None:
        """Binds `import m { a, b }` names. `quiet`: an early pass, once the type names are known, so field
        types and signatures can use imported types; names not found yet are bound by the final pass."""
        self.selective = {}
        saved = self.scope_slug
        for importer, sels in self._selective_raw.items():
            out: dict[str, str] = {}
            self.scope_slug = importer
            for local, (target, item, decl) in sels.items():
                key = f"{target}::{item}"
                found = self._decl_for(key)
                if found is None and quiet:
                    continue
                if found is None:
                    self._err(decl, f"`{item}` is not in that module.",
                              "Import a public function, type, or constant.")
                    continue
                if not getattr(found, "is_pub", False):
                    if quiet:
                        continue
                    self._err(decl, f"`{item}` is private.",
                              f"Put `{item}` under a `public` line, or drop it from the import list.")
                    continue
                out[local] = key
            self.selective[importer] = out
        self.scope_slug = saved

    def _visible_func(self, name: str) -> FuncInfo | None:
        key = self._resolve_simple(name)
        if key is None:
            return None
        info = self.funcs.get(key)
        if info is None or info.owner is not None:
            return None
        if not self._is_visible(info.decl):
            return None
        return info

    def _note_const(self, e: Name) -> None:
        key = self._resolve_simple(e.name)
        if key is not None and key in self.consts:
            e.const_key = key  # type: ignore[attr-defined]

    def _resolve_dyn(self, tref: TypeRef) -> str:
        """`dyn Shape`: the feature must exist; the canonical type is `dyn ` + its key."""
        if tref.qualifier:
            found = self._qualified_item(tref.qualifier, tref.base or "", tref)
            key = found if isinstance(found, str) else None
        else:
            key = self._resolve_simple(tref.base or "") or (tref.base if tref.base in self.features else None)
        if key is None or key not in self.features:
            known = ", ".join(f"`{k.split('::')[-1]}`" for k in self.features) or "none yet"
            self._err(tref, f"`dyn` needs a feature; `{tref.base}` is not one.",
                      f"Write `dyn` followed by a feature name. Features here: {known}.")
            return ERR
        return "dyn " + key

    def _resolve(self, tref: TypeRef) -> str:
        """Validates type name in source."""
        if getattr(tref, "is_dyn", False):
            return self._resolve_dyn(tref)
        if tref.name in SIMD_TYPES and not tref.args and tref.elem is None and not tref.qualifier:
            return tref.name
        pre = getattr(tref, "resolved", None)
        if pre is not None:  # synthesized by the checker (tuple literal element types)
            return pre
        if getattr(tref, "is_fn", False):
            boxed = getattr(tref, "fn_boxed", False)
            ps = [self._resolve(p) for p in tref.fn_params]
            ret = self._resolve(tref.fn_ret) if tref.fn_ret is not None else VOID
            if ERR in ps or ret == ERR:
                return ERR
            for p_node, p_ty in zip(tref.fn_params, ps):
                if is_slice_type(p_ty) or self._drop(p_ty):
                    self._err(p_node, f"Function pointer parameters cannot be `{p_ty}`.",
                              "Slices and heap-owning values cannot be passed through function pointers.")
                    return ERR
            if is_slice_type(ret):
                self._err(tref, "Function pointers cannot return slices.")
                return ERR
            return make_boxed_fn(ps, ret) if boxed else make_fn(ps, ret)
        if getattr(tref, "is_ptr", False):
            assert tref.elem is not None
            if tref.elem.name == "void" and not tref.elem.args and not getattr(tref.elem, "is_ptr", False):
                return make_ptr("void", tref.ptr_mut)
            elem_ty = self._resolve(tref.elem)
            if elem_ty == ERR:
                return ERR
            owned = self._drop(elem_ty) or elem_ty in self.enums or heap_kind(elem_ty) is not None
            if elem_ty == "str" or is_slice_type(elem_ty) or is_array_type(elem_ty) or (owned and not self.unsafe_depth):
                self._err(tref, f"`{make_ptr(elem_ty, tref.ptr_mut)}` is invalid: pointer can only point to numeric, `bool`, "
                                "struct, `void`, or another pointer.",
                          "Use element pointer for array/slice: `*u8`; for string use `string_to_cstr(s)`.")
                return ERR
            return make_ptr(elem_ty, tref.ptr_mut)
        if getattr(tref, "is_slice", False):
            assert tref.elem is not None
            elem_ty = self._resolve(tref.elem)
            if elem_ty == ERR:
                return ERR
            return f"[]{elem_ty}"
        if getattr(tref, "is_array", False):
            assert tref.elem is not None and tref.size_expr is not None
            elem_ty = self._resolve(tref.elem)
            if elem_ty == ERR:
                return ERR
            val = self._eval_const(tref.size_expr)
            if val is None or not isinstance(val, int) or val <= 0:
                self._err(tref.size_expr, "Array size must be a positive constant integer.")
                return ERR
            return f"[{val}]{elem_ty}"
        if getattr(tref, "is_bounded", False) or is_bounded_int(tref.name):
            base, lo, hi = bounded_int_info(tref.name)
            if lo >= hi:
                self._err(tref, f"Invalid bounded integer range `{lo}..{hi}`: lower bound must be less than upper bound.")
                return ERR
            return make_bounded_int(base, lo, hi)
        if tref.args:  # Pair[i32, f64]
            assert tref.base is not None
            base = tref.base
            if tref.qualifier:
                found = self._qualified_item(tref.qualifier, base, tref)
                if found is False or found is None:
                    if found is None:
                        self._err(tref, f"Unknown module `{tref.qualifier}`.",
                                  f"Import it in this file: `import {tref.qualifier}`.")
                    return ERR
                base = found
            else:
                simple = self._resolve_simple(base)
                if simple is not None:
                    base = simple
            return self._resolve_app(base, tref.args, tref)
        if tref.name in self.tparams:  # T -> concrete type during instantiation
            bound = self.tparams[tref.name]
            if is_const_arg(bound) and not getattr(tref, "const_ok", False):
                self._err(tref, f"`{tref.name}` is a constant parameter (a number), not a type.",
                          f"Use `{tref.name}` as an array length (`[{tref.name}]T`) or as a value in the body.",
                          rule="generic-args")
                return ERR
            return bound
        if tref.name.isdigit() and not tref.args:  # `Grid[2, 3]`: the value of a constant parameter
            if getattr(tref, "const_ok", False):
                return tref.name
            self._err(tref, f"`{tref.name}` is a number, not a type.", rule="generic-args")
            return ERR
        if tref.qualifier:
            found = self._qualified_item(tref.qualifier, tref.name, tref)
            if found is False or found is None:
                if found is None:
                    self._err(tref, f"Unknown module `{tref.qualifier}`.",
                              f"Import it in this file: `import {tref.qualifier}`.")
                return ERR
            cname = found
        else:
            simple = self._resolve_simple(tref.name)
            cname = simple if simple is not None else TYPE_ALIASES.get(tref.name, tref.name)
        if cname in PRIMS or cname in self.structs or cname in self.enums:
            return cname
        if tref.name in HEAP_BUILTINS:
            self._err(tref, f"`{tref.name}` is a generic type; type argument required.", f"Write as `{tref.name}[T]`.")
            return ERR
        generic = self.generic_structs.get(cname) or self.generic_enums.get(cname)
        if generic is not None:
            self._err(tref, f"`{tref.name}` is a generic type; type arguments required.",
                      f"Write as `{make_generic(tref.name, generic.type_params)}` (type arguments are always explicit).")
            return ERR
        pool = [n for n in list(PRIMS) + list(BUILTIN_TYPE_ALIASES) + list(self.structs) + list(self.enums)
                + list(self.generic_structs) + list(self.generic_enums) + ["string", "List", "Box", "Optional", "Result"]
                if "::" not in n and "[" not in n]
        near = friendly.nearest(tref.name, pool, friendly.TYPE_SYNONYMS)
        hint = f"Did you mean: `{near}`?" if near else \
            "Types: i32, i64, f32, f64, bool, string, or your own struct/enum."
        fixes = [friendly.rename_fix(tref.line, tref.col, tref.name, near, getattr(tref, "filename", None),
                                     "safe" if friendly.TYPE_SYNONYMS.get(tref.name) == near else "likely")] \
            if near and tref.line else []
        self._err(tref, f"Unknown type `{tref.name}`.", hint, fixes=fixes)
        return ERR

    def _implicit_convert(self, expected: str, actual: str, node: Node) -> bool:
        """Conversions that cannot lose information happen by themselves; the node is rewritten in place."""
        if not isinstance(node, Expr):
            return False
        src = bounded_int_info(actual)[0] if is_bounded_int(actual) else actual
        if expected in NUMERIC and src in NUMERIC and src != expected:
            if expected in friendly.WIDENS.get(src, ()) or self._counter_fits(node, expected):
                friendly.wrap_in_cast(node, expected)
                return True
            return False
        if expected == "string" and actual == "str":
            friendly.wrap_in_to_string(node)
            return True
        return False

    def _counter_fits(self, node: Node, target: str) -> bool:
        """`for i in 0..10`: `i` is an `i32`, but every value it takes also fits `usize`, `u8`, ..."""
        if not isinstance(node, Name):
            return False
        var = self._lookup(node.name)
        if var is None or var.lit_range is None:
            return False
        return friendly.int_fits(target, *var.lit_range)

    def _mismatch_fixes(self, expected: str, actual: str, node: Node) -> list[Fix]:
        """The edit that makes `actual` into `expected`, when there is a standard one."""
        base = bounded_int_info(actual)[0] if is_bounded_int(actual) else actual
        if expected in NUMERIC and base in NUMERIC:
            return friendly.wrap_fix(node, f"{expected}(", ")", f"Convert with `{expected}(...)`")
        if expected == "str" and actual == "string":
            return friendly.wrap_fix(node, "", ".as_str()", "View it as `str` with `.as_str()`")
        return []

    def _expect_type(self, expected: str, actual: str, node: Node, widen: bool = True) -> bool:
        if ERR in (expected, actual) or expected == actual:
            return True
        if widen and self._implicit_convert(expected, actual, node):
            return True
        if is_boxed_fn(expected):
            boxed = self._box_into(expected, actual, node)
            if boxed is not None:
                return boxed
        if is_dyn_type(expected) and not is_dyn_type(actual):
            return self._dyn_into(expected, actual, node)
        if is_fn_type(expected) and is_boxed_fn(actual):
            self._err(node, f"A `{actual}` closure value cannot be used where a plain `{expected}` pointer is expected.",
                      f"Change the parameter type to `{'F' + expected[1:]}` to accept closures.")
            return False
        if actual in self.closures:
            if is_fn_type(expected):
                self._err(node, "A lambda that captures variables cannot be stored or returned as a `fn(...)` value.",
                          "Pass it directly to a parameter of type `fn(...)`, call it where it is defined, "
                          "or pass the captured values as parameters.")
            else:
                self._err(node, f"Type mismatch: expected `{expected}`, found {self._closure_display(actual)}.")
            return False
        if is_ptr_type(expected) and is_ptr_type(actual) and ptr_const(expected) == ptr_const(actual) \
                and not ptr_is_mut(expected):
            return True  # implicit conversion `*mut T` -> `*T` (read-only view)
        if is_slice_type(expected):
            exp_elem = slice_elem_type(expected)
            if is_array_type(actual) and array_info(actual)[1] == exp_elem:
                return True
            if is_slice_type(actual) and slice_elem_type(actual) == exp_elem:
                return True
            if heap_kind(actual) == "List" and heap_inner(actual) == exp_elem:
                return True
        if is_bounded_int(expected):
            base, lo, hi = bounded_int_info(expected)
            if isinstance(node, IntLit):
                if lo <= node.value < hi:
                    return True
                self._err(node, f"{node.value} is out of bounds for `{expected}` (range [{lo}, {hi})).")
                return False
            if isinstance(node, Unary) and node.op == "-" and isinstance(node.operand, IntLit):
                val = -node.operand.value
                if lo <= val < hi:
                    return True
                self._err(node, f"{val} is out of bounds for `{expected}` (range [{lo}, {hi})).")
                return False
            if is_bounded_int(actual):
                _, a_lo, a_hi = bounded_int_info(actual)
                if a_lo >= lo and a_hi <= hi:
                    return True
                self._err(node, f"Range `[{a_lo}, {a_hi})` does not fit in expected range `[{lo}, {hi})` of `{expected}`.")
                return False
            self._err(node, f"Expected bounded integer `{expected}`, but got `{actual}`.")
            return False
        if is_bounded_int(actual):
            base, _, _ = bounded_int_info(actual)
            if expected in INTS or expected == "int" or expected == base:
                return True
        hint = "Only conversions that keep every value happen by themselves (`i32` to `i64`, `f32` to `f64`)."
        fixes = self._mismatch_fixes(expected, actual, node) if widen else []
        if not widen:
            hint = (f"A reference points at the value itself, so its type must be exactly `{expected}`. "
                    f"Declare the variable as `{expected}`.")
        elif fixes:
            hint = f"This conversion can lose information, so it is written out: `{expected}(...)`." \
                if expected in NUMERIC else f"Write `.as_str()` to view the `string` as a `str`."
        if isinstance(node, IntLit) and expected in FLOATS:
            hint = f"Write floating-point number: `{node.value}.0`"
            fixes = [friendly.rename_fix(node.line, node.col, str(node.value), f"{node.value}.0",
                                         getattr(node, "filename", None), "safe")] if node.length == len(str(node.value)) else []
        elif isinstance(node, FloatLit) and expected in INTS:
            hint = f"`{expected}` is an integer type; write a number without fractional part."
        self._err(node, f"Type mismatch: expected `{expected}`, found `{actual}`.", hint, fixes=fixes)
        return False

    # -- entry point -----------------------------------------------
    def check(self) -> None:
        self._init_modules()
        self._collect_features()
        self._collect_types()
        self._collect_consts()
        self._collect_externs()
        self._collect_funcs()
        self._finish_selective()
        self._apply_feature_defaults()
        self._collect_consts(comptime_pass=True)  # constants calling `comptime fn`: after signatures are known
        self._check_generic_params()
        self._infer_ret_origins()
        if self.require_main:
            self._check_main()
        check_attributes(self.program, self.diags)
        # Bodies checked via work queue: new function instances added during instantiation.
        # A Core function body is checked only when the program uses it (`_check_used_core`).
        self.pending = [i for i in self.funcs.values()
                        if not i.is_extern and not i.is_instance and not self._is_lambda(i)
                        and not getattr(i.decl, "from_prelude", False)]
        while self.pending:
            self._check_function(self.pending.pop(0))
        self._queue_unreached_lambdas()  # a lambda body is checked where the lambda is reached (captures)
        while self.pending:
            self._check_function(self.pending.pop(0))
        self._check_used_core()
        self._instantiate_drops()
        self._check_allocator()
        self._check_against_bounds()
        self._check_type_cycles()  # re-check for types created via generic instantiation
        self._check_instance_cnames()
        self._report_untyped_none()

    def _check_used_core(self) -> None:
        """Checks the bodies of the Core functions the program reaches, transitively."""
        core = _core_funcs(self)
        done: set[str] = set()
        work: list[Node] = [d for d in self.decls if isinstance(d, (FuncDecl, ConstDecl))
                            and not getattr(d, "from_prelude", False)] + list(self.instances)
        seen_instances = len(self.instances)
        while work:
            for key in _core_refs(work.pop(), core):
                if key in done:
                    continue
                done.add(key)
                info = self.funcs.get(key)
                if info is not None:
                    self._check_function(info)
                    while self.pending:
                        self._check_function(self.pending.pop(0))
                work.append(core[key])
            if len(self.instances) > seen_instances:  # a Core body instantiated more generic code
                work.extend(self.instances[seen_instances:])
                seen_instances = len(self.instances)

    def _check_allocator(self) -> None:
        """`allocator alloc, resize, free`: three functions with the C allocator's shapes."""
        from .ast_nodes import AllocatorDecl
        found = [d for d in self.decls if isinstance(d, AllocatorDecl)]
        self.program.allocator = None  # type: ignore[attr-defined]
        if not found:
            return
        for extra in found[1:]:
            self._err(extra, "A program has one `allocator`.", "Delete the second `allocator` line.")
        d = found[0]
        want = {"alloc": (["usize"], "*mut u8"), "resize": (["*mut u8", "usize"], "*mut u8"), "free": (["*mut u8"], "void")}
        shown = {"alloc": "fn NAME(size: usize) -> *mut u8", "resize": "fn NAME(p: *mut u8, size: usize) -> *mut u8",
                 "free": "fn NAME(p: *mut u8)"}
        keys = []
        self._enter(d)
        for role in ("alloc", "resize", "free"):
            name = getattr(d, role)
            info = self._visible_func(name)
            if info is None or info.is_extern:
                self._err(d, f"`allocator`: no Greengold function named `{name}` (the {role} function).",
                          f"Define `{shown[role].replace('NAME', name)}`.")
                return
            got = ([p.ty for p in info.params], info.ret)
            if got != want[role]:
                self._err(info.decl, f"`{name}` is the allocator's {role} function: it must be "
                                     f"`{shown[role].replace('NAME', name)}`.")
                return
            keys.append(info.key)
        self.program.allocator = tuple(keys)  # type: ignore[attr-defined]

    def _instantiate_drops(self) -> None:
        """Every generic instance with a destructor needs its `drop` method generated: codegen calls it."""
        done: set[str] = set()
        while True:
            todo = [ty for ty, info in list(self.structs.items()) + list(self.enums.items())
                    if info.user_drop and generic_parts(ty) is not None and ty not in done]
            if not todo:
                return
            for ty in todo:
                done.add(ty)
                if f"{ty}.drop" not in self.funcs:
                    info = self.structs.get(ty) or self.enums.get(ty)
                    self._method_template_info(ty, "drop", info.decl)
            while self.pending:
                self._check_function(self.pending.pop(0))

    def _apply_feature_defaults(self) -> None:
        """Synthesizes default methods for structs and enums that satisfy features."""
        user_methods = {(d.owner, d.name) for d in self.decls if isinstance(d, FuncDecl) and d.owner is not None}
        synthesized_from: dict[tuple[str, str], str] = {}

        changed = True
        while changed:
            changed = False
            candidates = [(s, False, []) for s in self.structs] + \
                         [(e, False, []) for e in self.enums] + \
                         [(s, True, list(self.generic_structs[s].type_params)) for s in self.generic_structs] + \
                         [(e, True, list(self.generic_enums[e].type_params)) for e in self.generic_enums]

            for target_name, is_generic, owner_params in candidates:
                for feature_name, fdecl in self.features.items():
                    probs = self._feature_problems(target_name, feature_name)
                    if probs:
                        continue

                    for m in fdecl.methods:
                        if not m.body:
                            continue

                        key = (target_name, m.name)
                        if key in user_methods:
                            continue

                        if key in synthesized_from:
                            prev_feature = synthesized_from[key]
                            if prev_feature != feature_name:
                                self._err(m, f"Conflicting default implementations of method `{m.name}` for `{target_name}` from features `{prev_feature}` and `{feature_name}`.",
                                          f"Define `fn {target_name}.{m.name}` to resolve ambiguity.")
                            continue

                        fn_copy = copy.deepcopy(m)
                        fn_copy.from_feature_default = True  # type: ignore[attr-defined]
                        fn_copy.owner = target_name
                        fn_copy.owner_params = list(owner_params)
                        subst_self_func(fn_copy, target_name, owner_params)

                        self.decls.append(fn_copy)
                        self.program.decls.append(fn_copy)
                        synthesized_from[key] = feature_name

                        if is_generic:
                            self._register_method_template(fn_copy)
                        else:
                            self._declare_function(fn_copy, f"{target_name}.{fn_copy.name}")

                        changed = True

    def _check_instance_cnames(self) -> None:
        """Verifies instance names (Pair_i32_f64 ...) do not clash with another C definition."""
        user = {n for n in list(self.structs) + list(self.enums) if generic_parts(n) is None}
        user |= set(self.consts)
        user |= {i.key if i.is_extern else func_cname(i.key) for i in self.funcs.values() if not i.is_instance}
        seen: dict[str, str] = {}
        for cn, what, node in self.instance_cnames:
            if cn in user or seen.get(cn, what) != what:
                other = seen.get(cn, "user definition")
                self._err(node, f"Name emitted to C `{cn}` conflicts between `{what}` and `{other}`.",
                          "Change one of the type or function names.")
            seen.setdefault(cn, what)

    def _comptime_fns(self) -> set[str]:
        return {d.name for d in self.decls if isinstance(d, FuncDecl) and d.is_comptime and d.owner is None}

    def _calls_comptime(self, e: object) -> bool:
        names = self._comptime_fns()
        found = []

        def walk(n: object) -> None:
            if isinstance(n, Call) and n.callee in names:
                found.append(n)
            if isinstance(n, Node):
                for v in n.__dict__.values():
                    if isinstance(v, Node):
                        walk(v)
                    elif isinstance(v, list):
                        for x in v:
                            walk(x)
        walk(e)
        return bool(found)

    def _collect_consts(self, comptime_pass: bool = False) -> None:
        for d in self.decls:
            if not isinstance(d, ConstDecl):
                continue
            if self._calls_comptime(d.value) != comptime_pass:
                continue
            self._enter(d)
            key = self._sym_key(d, d.name)
            if self._type_kind(key) or self._type_kind(d.name):
                self._err(d, f"`{d.name}` is a type name, cannot be a constant name.")
                continue
            if key in self.consts:
                self._err(d, f"`{d.name}` constant is already defined.", "Constant names must be unique.")
                continue
            if d.name in PRIMS or d.name in BUILTIN_TYPE_ALIASES or d.name in BUILTINS or d.name in PRELUDE_NAMES:
                self._err(d, f"`{d.name}` is a reserved name.")
                continue

            self._validate_const_expr(d.value)

            if d.type_ref:
                exp_ty = self._resolve(d.type_ref)
                val_ty = self._expr(d.value, exp_ty)
                if ERR not in (exp_ty, val_ty):
                    self._expect_type(exp_ty, val_ty, d.value)
                final_ty = exp_ty
            else:
                val_ty = self._expr(d.value)
                final_ty = val_ty
            d.ty = final_ty
            if is_slice_type(final_ty):
                self._err(d, "Slice (`[]T`) cannot be a constant type.")
            if d.is_static and final_ty != ERR and (self._moves(final_ty) or final_ty == "str"):
                self._err(d, f"A `static` holds plain data; `{final_ty}` is not.",
                          "Use numbers, `bool`, arrays, and structs of them.")

            eval_val = self._eval_const(d.value)
            if final_ty in INTS and eval_val is not None:
                min_val, max_val = INT_RANGES[final_ty]
                if not (min_val <= eval_val <= max_val):
                    self._err(d.value, f"Constant value {eval_val} is out of range [{min_val}, {max_val}] for `{final_ty}`.")
            d.sym_key = key  # type: ignore[attr-defined]
            self.consts[key] = ConstInfo(key, final_ty, eval_val, d)

    def _validate_const_expr(self, e: Expr) -> None:
        """Constant expressions can only contain literals, previously declared constants, arithmetic/bitwise/cast operations."""
        if isinstance(e, (IntLit, FloatLit, BoolLit, StrLit, CharLit)):
            return
        if isinstance(e, Name) and e.name in SHORT_CTORS:  # `None`
            return
        if isinstance(e, Call) and e.callee in SHORT_CTORS:  # `Valid(3)`, `Ok(1)`
            for a in e.args:
                self._validate_const_expr(a)
            return
        if isinstance(e, (FieldAccess, MethodCall)) and isinstance(e.obj, Name) and self._enum_target(e.obj) is not None:
            for a in getattr(e, "args", []):  # `Color.Red`, `Shape.Circle(1.5)`
                self._validate_const_expr(a)
            return
        if isinstance(e, Name):
            key = self._resolve_simple(e.name)
            if key is None or key not in self.consts:
                if any(isinstance(d, ConstDecl) and d.name == e.name for d in self.decls):
                    self._err(e, f"`{e.name}` constant has not been declared yet.",
                              "Constants can only use constants declared before them.")
                else:
                    self._err(e, f"`{e.name}` is not a defined constant.",
                              "Constant expression can only use previously declared constants and literals.")
            return
        if isinstance(e, Unary):
            self._validate_const_expr(e.operand)
            return
        if isinstance(e, Binary):
            self._validate_const_expr(e.left)
            self._validate_const_expr(e.right)
            return
        if isinstance(e, Cast):
            self._validate_const_expr(e.expr)
            return
        if isinstance(e, Call) and e.callee in self._comptime_fns():
            for a in e.args:
                self._validate_const_expr(a)
            return
        if isinstance(e, ArrayLit):  # `[1, 2, 3]`, `Point{ x: 1, y: 2 }`: data made of constants
            for el in e.elements:
                self._validate_const_expr(el)
            return
        if isinstance(e, ArrayRepeatLit):
            self._validate_const_expr(e.value)
            self._validate_const_expr(e.count)
            return
        if isinstance(e, StructLit):
            for f in e.fields:
                self._validate_const_expr(f.value)
            return
        self._err(e, f"Cannot use `{type(e).__name__}` in constant expression.",
                  "Only literals, previously declared constants, and arithmetic/bitwise/cast operations may be used.")

    # -- 1. structs ------------------------------------------------
    def _type_kind(self, name: str) -> str | None:
        """If `name` is struct/enum name, returns "struct"/"enum", otherwise None."""
        if name in self.structs:
            return "struct"
        if name in self.enums:
            return "enum"
        return None

    def _collect_types(self) -> None:
        """Collects struct and enum declarations: first names, then field/payload types."""
        decls = [d for d in self.decls if isinstance(d, (StructDecl, EnumDecl))]
        for d in decls:
            kind = "struct" if isinstance(d, StructDecl) else "enum"
            if d.type_params:
                self._register_generic_type(d)
            elif d.name in PRIMS or d.name in BUILTIN_TYPE_ALIASES or d.name in self._reserved_names(d):
                self._err(d, f"`{d.name}` is a reserved name, cannot be a {kind} name.")
            else:
                canon = self._sym_key(d, d.name)
                if (canon in self.structs or canon in self.enums or canon in self.generic_structs
                        or canon in self.generic_enums):
                    self._err(d, f"`{d.name}` is already defined.", f"{kind.capitalize()} names must be unique."
                              if kind == "struct" else "Type names must be unique.")
                elif kind == "struct":
                    self.structs[canon] = StructInfo(d.name if canon == d.name else canon, {}, d)  # type: ignore[arg-type]
                    self.type_order.append(canon)
                else:
                    self.enums[canon] = EnumInfo(d.name if canon == d.name else canon, {}, d)  # type: ignore[arg-type]
                    self.type_order.append(canon)
        self._finish_selective(quiet=True)
        self._collect_drop_owners()
        for d in decls:
            self._enter(d)
            if isinstance(d, StructDecl):
                info = self.structs.get(self._sym_key(d, d.name))
                if info is not None and info.decl is d:
                    self._fill_struct(info)
            else:
                einfo = self.enums.get(self._sym_key(d, d.name))
                if einfo is not None and einfo.decl is d:
                    self._fill_enum(einfo)
        self._check_type_cycles()

    def _collect_drop_owners(self) -> None:
        """Types with a destructor. Known before any field or signature is resolved, because `drop` makes
        the type move-only, and that decides parameter modes."""
        for d in self.decls:
            if not isinstance(d, FuncDecl) or d.name != "drop" or d.owner is None:
                continue
            self._enter(d)
            ok = (len(d.params) == 1 and d.params[0].name == "self" and d.params[0].mode == "lend"
                  and d.ret is None and not d.type_params and not d.ret_view)
            if not ok:
                self._err(d, "A destructor is written `fn drop(self: lend Self)`: no other parameter and no result.",
                          "Change the signature to `fn drop(self: lend Self):`.", rule="drop-signature")
            if getattr(d, "owner_qualifier", None):
                self._err(d, "`drop` must be defined in the file that defines the type.",
                          "Move this `drop` next to the type.", rule="drop-signature")
                continue
            canon = self._resolve_simple(d.owner) or d.owner
            if canon in self.generic_structs or canon in self.generic_enums or canon in self.structs or canon in self.enums:
                self.drop_owners.add(canon)

    def _fill_struct(self, info: StructInfo) -> None:
        d = info.decl
        info.handle = is_handle_decl(d)
        info.user_drop = self._sym_key(d, d.name) in self.drop_owners
        for f in d.fields:
            ty = self._resolve(f.type_ref)
            f.ty = ty
            if getattr(d, "is_union", False) and ty != ERR and (
                    self._drop(ty) or f.mode or ty == "str" or is_slice_type(ty) or self._moves(ty)):
                self._err(f, f"A `union` field holds plain data; `{f.name}: {ty}` is not.",
                          "Use numbers, `bool`, pointers, arrays, and structs of them.")
            if getattr(d, "is_extern", False) and ty != ERR:
                base = array_info(ty)[1] if is_array_type(ty) else ty
                ok = (base in NUMERIC or base == "bool" or is_ptr_type(base) or is_fn_type(base)
                      or (base in self.structs and (getattr(self.structs[base].decl, "is_extern", False)
                                                    or getattr(self.structs[base].decl, "is_union", False))))
                if not ok or f.mode:
                    self._err(f, f"`extern struct` field must be C-compatible (numeric, `bool`, pointer, function pointer, `extern struct`, `union`, or an array thereof); found `{ty}`.",
                              "`string`, slice, enum, heap types and reference fields cannot be inside `extern struct`.")
            if f.name in info.fields:
                self._err(f, f"Field `{f.name}` defined twice in struct `{d.name}`.")
            else:
                info.fields[f.name] = ty
                info.field_pub[f.name] = bool(getattr(f, "is_pub", False))
                if f.mode:
                    info.field_modes[f.name] = f.mode
                    if f.tied_to is not None:
                        info.field_tied[f.name] = f.tied_to
                    if is_array_type(ty):
                        self._err(f, f"Reference field `{f.name}` cannot be an array.",
                                  "Store a reference to the variable that owns the array, or use a slice parameter.")

    def _fill_enum(self, info: EnumInfo) -> None:
        d = info.decl
        info.user_drop = self._sym_key(d, d.name) in self.drop_owners
        for v in d.variants:
            payload: list[str] = []
            for tref in v.payload:
                ty = self._resolve(tref)
                if is_slice_type(ty):
                    self._err(tref, "Slice (`[]T`) cannot be an enum payload; can only be a function parameter.",
                              "Use array `[N]T` instead of slice.")
                    ty = ERR
                payload.append(ty)
            if v.name in info.variants:
                self._err(v, f"Variant `{v.name}` defined twice in enum `{d.name}`.",
                          "Variant names must be unique within an enum.")
            else:
                info.variants[v.name] = VariantInfo(v.name, payload, len(info.variants))

    def _by_value_children(self, name: str) -> list[str]:
        """Struct/enum names contained by VALUE in type `name` (struct/enum, including array elements)."""
        if name in self.structs:
            si = self.structs[name]
            tys = [t for n, t in si.fields.items() if n not in si.field_modes]  # reference fields are not by-value
        else:
            tys = [t for v in self.enums[name].variants.values() for t in v.payload]
        out: list[str] = []
        for t in tys:
            while is_array_type(t):
                t = array_info(t)[1]
            if t in self.structs or t in self.enums:
                out.append(t)
        return out

    def _check_type_cycles(self) -> None:
        """A struct/enum cannot contain itself by value (even indirectly)."""
        state: dict[str, int] = {}  # 1: visiting, 2: done
        reported: set[str] = getattr(self, "_cycle_reported", set())
        self._cycle_reported = reported

        def visit(name: str) -> None:
            state[name] = 1
            for child in self._by_value_children(name):
                if state.get(child) == 1 and child not in reported:
                    reported.add(child)
                    if child in self.structs:
                        self._err(self.structs[child].decl,
                                  f"`{child}` contains itself by value (infinite size).",
                                  "A struct cannot contain itself; hold the inner value in a `Box` or a `List`.")
                    else:
                        self._err(self.enums[child].decl,
                                  "enum cannot contain itself by value (heap coming in v3).",
                                  f"`{child}` refers to itself in payload (even indirectly); break the cycle.")
                elif child not in state:
                    visit(child)
            state[name] = 2

        for name in list(self.structs) + list(self.enums):
            if name not in state:
                visit(name)

    # -- 2. extern functions ---------------------------------------
    def _collect_externs(self) -> None:
        for d in self.decls:
            if not isinstance(d, ExternFuncDecl):
                continue
            self._enter(d)
            name = self._sym_key(d, d.name)
            d.lookup_key = name  # type: ignore[attr-defined]
            if self._type_kind(name) or self._type_kind(d.name):
                self._err(d, f"`{d.name}` is a type name, cannot be an extern function name.")
                continue
            if name in self.consts:
                self._err(d, f"`{d.name}` is a constant name, cannot be an extern function name.")
                continue
            if d.name in PRIMS or d.name in BUILTIN_TYPE_ALIASES or d.name in BUILTINS or d.name in PRELUDE_NAMES:
                self._err(d, f"`{d.name}` is a reserved name.")
                continue
            if name in self.funcs:
                if not self.funcs[name].is_extern:
                    self._err(d, f"Cannot define both a normal Greengold function and an extern function with the same name: `{name}`.")
                else:
                    self._err(d, f"`{name}` is already defined.")
                continue

            params: list[ParamInfo] = []
            seen: set[str] = set()
            for p in d.params:
                ty = self._resolve(p.type_ref)
                p.ty = ty
                if p.name in seen:
                    self._err(p, f"Parameter `{p.name}` is defined twice.")
                seen.add(p.name)

                # Extern parameter restrictions
                if p.mode == "consume":
                    self._err(p, "cannot use `consume` parameter in extern functions.")
                elif is_slice_type(ty):
                    self._err(p, "cannot use slice parameter in extern functions.")
                elif is_array_type(ty):
                    self._err(p, "cannot use array parameter in extern functions.")
                elif p.mode in ("lend", "read"):
                    if ty not in PRIMS and ty not in self.structs and ty != ERR:
                        self._err(p, f"type `{ty}` cannot be passed with `{p.mode}` in extern functions.")
                else:  # value mode (default)
                    if ty in self.structs and self._c_struct_problem(ty) is None:
                        pass  # by value, following the platform's C rules (cabi.py)
                    elif ty not in (NUMERIC | {"bool", "str"}) and ty != ERR and not is_ptr_type(ty) and not is_fn_type(ty):
                        if ty in self.structs:
                            self._err(p, f"struct `{ty}` cannot be passed to C by value: {self._c_struct_problem(ty)}.",
                                      f"Write `{p.name}: read {ty}` or `{p.name}: *{ty}` to pass a pointer.")
                        else:
                            self._err(p, f"parameter type `{ty}` is not supported in extern functions.")

                params.append(ParamInfo(p.name, ty, p.mode or "val", p))

            ret = self._resolve(d.ret) if d.ret else VOID
            d.ret_ty = ret
            if ret == "str":
                self._err(d.ret, "extern functions cannot return `string`.")
            elif ret in self.structs and self._c_struct_problem(ret) is None:
                pass  # returned by value, following the platform's C rules (cabi.py)
            elif ret != VOID and ret not in (NUMERIC | {"bool"}) and ret != ERR and not is_ptr_type(ret):
                why = f": {self._c_struct_problem(ret)}" if ret in self.structs else ""
                self._err(d.ret, f"extern functions cannot return `{ret}`{why}; they return numbers, bool, pointers, "
                                 "C-compatible structs, or nothing.",
                          "For other C results, write a wrapper that returns a pointer or takes a `lend` out-parameter.")

            self.funcs[name] = FuncInfo(name, params, ret, None, d, is_extern=True, header=d.header)
            self.free_funcs.add(name)

    def _c_struct_problem(self, ty: str, seen: frozenset[str] = frozenset()) -> str | None:
        """Why a struct cannot cross to C by value (None when it can): only plain C data inside."""
        info = self.structs.get(ty)
        if info is None:
            return f"`{ty}` is not a struct"
        if ty in seen:
            return f"`{ty}` contains itself"
        if getattr(info.decl, "is_union", False) or getattr(info.decl, "packed", False) or getattr(info.decl, "align", 0):
            return f"`{ty}` is a union, `packed`, or `align(N)`"
        if info.field_modes or info.handle or info.user_drop:
            return f"`{ty}` holds a reference, an OS handle, or has `drop`"
        for fname, fty in info.fields.items():
            base = array_info(fty)[1] if is_array_type(fty) else fty
            if base in NUMERIC or base == "bool" or is_ptr_type(base) or is_fn_type(base):
                continue
            if base in self.structs:
                inner = self._c_struct_problem(base, seen | {ty})
                if inner is None:
                    continue
                return inner
            return f"field `{fname}: {fty}` is not C data"
        return None

    # -- 3. functions ----------------------------------------------
    def _collect_funcs(self) -> None:
        for d in self.decls:
            if not isinstance(d, FuncDecl):
                continue
            self._enter(d)
            if d.owner is not None:
                qual = getattr(d, "owner_qualifier", None)
                if qual:
                    found = self._qualified_item(qual, d.owner, d)
                    if isinstance(found, str):
                        d.owner = found
                else:
                    canon_owner = self._resolve_simple(d.owner)
                    if canon_owner is not None:
                        d.owner = canon_owner
            if d.type_params:
                self._register_generic_fn(d)
            elif d.owner is not None and (d.owner_params or d.owner in self.generic_structs
                                          or d.owner in self.generic_enums):
                self._register_method_template(d)
            else:
                key = self._sym_key(d, d.name) if d.owner is None else f"{d.owner}.{d.name}"
                self._declare_function(d, key)

    def _declare_function(self, d: FuncDecl, key: str, instance: bool = False) -> FuncInfo | None:
        """Resolves function/method signature and registers under `self.funcs[key]` (instance=True: generic instance)."""
        saved_scope = self.scope_slug
        self._enter(d)
        params: list[ParamInfo] = []
        seen: set[str] = set()
        for p in d.params:
            ty = getattr(p, "fixed_ty", None) or self._resolve(p.type_ref)
            p.ty = ty
            if p.name in seen:
                self._err(p, f"Parameter `{p.name}` is defined twice.")
            seen.add(p.name)
            # `consume T` written with type parameter in generic instance: not an error for copyable types.
            generic_param = instance and self._mentions_tparam(p.type_ref)
            if p.mode == "" and self._moves(ty):
                # Heap-owning values are never copied. The mode is inferred from the body: `read` by
                # default, `lend` when the body mutates it, `consume` when the body moves it. A generic
                # function is inferred per instance: `T = i32` and `T = List[i32]` may differ.
                p.mode = self.inferred.get(_param_key(p, d), "read")
                p.mode_inferred = True  # type: ignore[attr-defined]
                p.mode_key = _param_key(p, d)  # type: ignore[attr-defined]
            elif p.mode == "" and is_slice_type(ty):
                # A slice written without a mode stays a read-only view until the body changes an
                # element; then it is `lend` (never `consume`: a slice cannot be moved).
                p.mode_key = _param_key(p, d)  # type: ignore[attr-defined]
                p.mode_slice = True  # type: ignore[attr-defined]
                if self.inferred.get(p.mode_key) == "lend":
                    p.mode = "lend"
                    p.mode_inferred = True  # type: ignore[attr-defined]
            if p.mode == "consume":
                if is_slice_type(ty):
                    self._err(p, "Slice cannot be moved.", "Slices are not copied and cannot be moved.")
                elif not generic_param and (ty in PRIMS or (is_array_type(ty) and array_info(ty)[1] in PRIMS)):
                    self._err(p, f"{ty} is copied, `consume` is not needed.",
                              f"Write `{p.name}: {ty}`" + (" (`lend` if you want to mutate)." if ty in PRIMS else "."))
            params.append(ParamInfo(p.name, ty, p.mode or "val", p, generic=generic_param))
        ret = self._resolve(d.ret) if d.ret else VOID
        d.ret_ty = ret

        if d.owner is not None and not self._valid_receiver(d, params):
            self.scope_slug = saved_scope
            return None
        if d.owner is None and not instance:  # instance names already checked during template registration
            if d.name in BUILTINS or d.name in PRIMS or d.name in BUILTIN_TYPE_ALIASES or d.name in PRELUDE_NAMES:
                self._err(d, f"`{d.name}` is a reserved name.")
                self.scope_slug = saved_scope
                return None
            if key in self.consts or d.name in self.consts:
                self._err(d, f"`{d.name}` is a constant name, cannot be a function name.")
                self.scope_slug = saved_scope
                return None
            kind = self._type_kind(key) or self._type_kind(d.name)
            if kind:
                self._err(d, f"`{d.name}` is a {kind} name, cannot be a function name.")
                self.scope_slug = saved_scope
                return None
        if key in self.funcs:
            if self.funcs[key].is_extern:
                self._err(d, f"Cannot define both a normal Greengold function and an extern function with the same name: `{d.name}`.")
            else:
                self._err(d, f"`{d.name}` is already defined.", "Function names must be unique (there is no overloading).")
            self.scope_slug = saved_scope
            return None
        info = FuncInfo(key, params, ret, d.owner, d)
        if d.ret_view:
            info.ret_view = True
            info.ret_lend = d.ret_lend
            if not params:
                word = "lend" if d.ret_lend else "ref"
                self._err(d, f"`-> {word} T` requires at least one parameter: the reference is derived from a parameter.")
            elif d.ret_tied is not None and d.ret_tied not in {p.name for p in params}:
                self._err(d, f"`tied to {d.ret_tied}`: no parameter named `{d.ret_tied}`.",
                          f"Parameters: {', '.join(p.name for p in params)}.")
            elif d.ret_tied is not None:
                info.ret_origin = d.ret_tied
        self.funcs[key] = info
        if instance and info.ret_view and info.ret_origin is None and info.params:
            origin = self._scan_ret_origin(info)
            info.ret_origin = origin if isinstance(origin, str) and origin != "AMBIGUOUS" else info.params[0].name
        if d.owner is None and not instance:
            self.free_funcs.add(key)
        self.scope_slug = saved_scope
        return info

    def _infer_ret_origins(self) -> None:
        """Before bodies are checked, decide which parameter a `-> ref`/`-> lend` result is tied to.

        Callers use this so a stored reference is tied to the right argument. The body check
        confirms every `return` matches. Explicit `tied to` wins. Otherwise every return must
        derive from the same parameter; if that cannot be seen syntactically, the first parameter
        is the tie and a mismatch is reported when the body is checked.
        """
        pending = [i for i in self.funcs.values() if i.ret_view and not i.is_extern and i.ret_origin is None]
        changed = True
        while changed and pending:
            changed = False
            still: list[FuncInfo] = []
            for info in pending:
                origin = self._scan_ret_origin(info)
                if origin == "AMBIGUOUS":
                    self._err(info.decl, "Reference return comes from more than one parameter.",
                              "All `return`s must use the same parameter, or write `-> ref T tied to name`.")
                    info.ret_origin = info.params[0].name if info.params else None
                elif origin is None:
                    still.append(info)
                else:
                    info.ret_origin = origin
                    changed = True
            pending = still
        for info in pending:
            if info.params and info.ret_origin is None:
                info.ret_origin = info.params[0].name

    def _scan_ret_origin(self, info: FuncInfo) -> str | None:
        """Parameter name every reference return derives from, `AMBIGUOUS`, or None if not yet known."""
        ties: dict[str, str] = {}
        origins: list[str] = []
        flag = {"unresolved": False}

        def root_of(e: Expr) -> str | None:
            while isinstance(e, BorrowExpr):
                e = e.expr
            while isinstance(e, (FieldAccess, IndexAccess)):
                e = e.obj
            if isinstance(e, MethodCall):
                callee = self._method_by_name(e.method)
                if callee is not None and callee.ret_view:
                    origin = callee.ret_origin or callee.decl.ret_tied
                    if origin is None:
                        flag["unresolved"] = True
                        return None
                    idx = next((i for i, p in enumerate(callee.params) if p.name == origin), 0)
                    if idx == 0:
                        return root_of(e.obj)
                    if idx - 1 < len(e.args):
                        return root_of(e.args[idx - 1])
                    flag["unresolved"] = True
                    return None
                return root_of(e.obj)
            if isinstance(e, Call):
                callee = self.funcs.get(e.callee)
                if callee is not None and callee.ret_view:
                    origin = callee.ret_origin or callee.decl.ret_tied
                    if origin is None:
                        flag["unresolved"] = True
                        return None
                    idx = next((i for i, p in enumerate(callee.params) if p.name == origin), 0)
                    if idx < len(e.args):
                        return root_of(e.args[idx])
                    flag["unresolved"] = True
                    return None
                return None
            if isinstance(e, Name):
                return ties.get(e.name, e.name)
            if isinstance(e, BlockExpr):
                return None
            return None

        def note_binding(name: str, value: Expr) -> None:
            mode = ""
            if isinstance(value, BorrowExpr):
                mode = value.mode
            viewish = isinstance(value, (Call, MethodCall))
            if mode or viewish:
                r = root_of(value)
                if r:
                    ties[name] = r

        def walk(stmts: list[Stmt]) -> None:
            for s in stmts:
                if isinstance(s, VarDecl):
                    note_binding(s.name, s.value)
                elif isinstance(s, Assign) and isinstance(s.target, Name):
                    note_binding(s.target.name, s.value)
                elif isinstance(s, Return) and s.value is not None:
                    r = root_of(s.value)
                    if r:
                        origins.append(r)
                    else:
                        flag["unresolved"] = True
                elif isinstance(s, If):
                    for br in s.branches:
                        walk(br.body)
                    if s.else_body is not None:
                        walk(s.else_body)
                elif isinstance(s, (While, For, ForIn)):
                    walk(s.body)
                elif isinstance(s, Match):
                    for arm in s.arms:
                        walk(arm.body)
                elif isinstance(s, Defer):
                    walk([s.stmt])

        walk(info.decl.body)
        unresolved = flag["unresolved"]
        if unresolved and not origins:
            return None
        params = {p.name for p in info.params}
        got = [o for o in origins if o in params]
        if unresolved and len(set(got)) != 1:
            return None
        if not got:
            return None
        if len(set(got)) > 1:
            return "AMBIGUOUS"
        return got[0]

    def _method_by_name(self, method: str) -> FuncInfo | None:
        hits = [i for k, i in self.funcs.items() if k.endswith("." + method) and i.ret_view]
        if len(hits) == 1:
            return hits[0]
        return None

    def _valid_receiver(self, d: FuncDecl, params: list[ParamInfo]) -> bool:
        owner = d.owner
        shown = owner.replace("::", ".")
        if owner not in self.structs and owner not in self.enums and owner != "str":
            self._err(d, f"No struct named `{shown}`; cannot define method.",
                       f"First define `struct {shown}:` (or `enum {shown}:`).")
            return False
        if not params or params[0].name != "self":
            d.is_static = True  # type: ignore[attr-defined]  # associated function: `Type.name(args)`
            return True
        first = params[0]
        if first.ty != owner and first.ty != ERR:
            self._err(first.node, f"`self` type must be `{shown}`, found `{first.ty}`.")
            return False
        return True

    def _check_main(self) -> None:
        for d in self.decls:
            if (isinstance(d, FuncDecl) and d.name == "main" and d.owner is None
                    and (getattr(d, "module_slug", "") or "")):
                self._err(d, "`fn main` is only allowed in the program root.",
                          "Move `fn main` to the file you compile.")
        info = self.funcs.get("main")
        if info is None:
            self.diags.error("`fn main():` not found.", 1, 1, 1, "Write `fn main():` as program entry point.")
            return
        if info.params or info.ret != VOID:
            self._err(info.decl, "`main` takes no parameters and does not return a value.",
                      "Write as `fn main():`.")

    # -- 3. bodies ---------------------------------------------------
    def _check_function(self, info: FuncInfo) -> None:
        d = info.decl
        self._enter(d)
        self.cur = info
        self.tparams = info.bindings  # T -> concrete type in generic instance
        self.const_types = getattr(info, "const_types", {}) or {}
        self.depth = info.depth
        self.scopes = [{}]
        self.loop_depth = 0
        self.yields = []
        for p in info.params:
            kind = p.mode or "val"  # "val" | "consume" | "read" | "lend"
            self._declare(p.name, VarInfo(p.name, p.ty, p.mode in ("consume", "lend"), kind), p.node)
            if getattr(d, "async_wrapper", False) and not self._is_archetype(p.ty):
                why = thread_problem(p.ty, self.structs, self.enums)
                if why:
                    self._err(p.node, f"`{p.name}` of an `async fn` moves into a task, which may run later: {why}.",
                              "Take owned data (`string`, `List`), or share it read-only with `Arc`.",
                              rule="not-send", details={"value": p.name, "reason": why})
        self._block(d.body)
        if info.ret not in (VOID, ERR) and not _always_returns(d.body):
            self._err(d, f"Function `{d.name}` must return `{info.ret}`, but not all paths have a `return`.",
                      "Add `return value` at the end of the function (and all if/else arms).")
        self.cur = None
        self.tparams = {}
        self.depth = 0

    def _note_inferred(self, p: ParamInfo, display: str) -> None:
        """Explains an inferred parameter mode on the diagnostic just reported for the argument."""
        node = p.node
        if node is None or not getattr(node, "mode_inferred", False) or not self.diags.items:
            return
        if display.startswith("_list_"):  # `xs.sort()`: the Core helper's own parameter is not worth showing
            return
        why = "changes" if p.mode == "lend" else "keeps"
        self.diags.items[-1].notes.append(Note(node.line, node.col, max(len(node.name), 1),
                                               f"`{display}` {why} `{p.name}`, so it takes it as `{p.mode}` (inferred)"))

    def _infer_mode(self, root: VarInfo, mode: str) -> bool:
        """Records that inferred parameter `root` needs `mode` ("lend" or "consume").
        Returns True when it was recorded; check_program then re-checks with the stronger mode."""
        param = root.origin
        key = getattr(param, "mode_key", None)
        if not isinstance(param, Param) or key is None:
            return False
        if getattr(param, "mode_slice", False):
            if mode != "lend":
                return False
        elif not getattr(param, "mode_inferred", False):
            return False
        if _MODE_RANK[mode] > _MODE_RANK.get(self.mode_upgrades.get(key, "read"), 0):
            self.mode_upgrades[key] = mode
        return True

    def _declare(self, name: str, var: VarInfo, node: Node) -> None:
        if name in PRELUDE_NAMES:
            self._err(node, f"`{name}` is a reserved name (prelude), cannot be a variable name.", "Choose another name.")
        in_prelude = self.cur is not None and getattr(self.cur.decl, "from_prelude", False)
        if name in self.consts and not in_prelude:  # user constants do not reach into the Core library
            self._err(node, f"`{name}` is already defined as a global constant; shadowing is not allowed.",
                      "Choose another name.")
        key = self._resolve_simple(name)  # only names visible in this module's scope can clash
        if in_prelude and key is not None and not getattr(self._decl_for(key), "from_prelude", False):
            key = None  # user names do not reach into the Core library
        if key is not None and (key in self.free_funcs or key in self.structs or key in self.enums
                                or key in self.generic_structs or key in self.generic_enums):
            self._err(node, f"`{name}` conflicts with a function/struct name.", "Choose another name.")
        for scope in self.scopes:
            if name in scope:
                self._err(node, f"`{name}` is already defined; a second variable with the same name is not allowed.",
                          f"Assign to it with `{name} = ...`, or choose another name.")
                break
        var.origin = node
        self.scopes[-1][name] = var

    def _block(self, stmts: list[Stmt]) -> None:
        self.scopes.append({})
        for i, s in enumerate(stmts):
            if self._is_new_binding(s):  # `x = v` with no `x`: a declaration; later passes see a VarDecl
                s = stmts[i] = self._decl_from_assign(s)  # type: ignore[arg-type]
            elif self._is_existing_binding(s):  # bare `x = v` where `x` is an imported constant/static
                s = stmts[i] = self._assign_from_decl(s)  # type: ignore[arg-type]
            self._stmt(s)
            d = getattr(s, "desugared", None)
            if d is not None:  # `for` over an iterator: later passes see the plain `while`/`match` form
                stmts[i] = d
        self.scopes.pop()

    # -- statements ------------------------------------------------------
    def _stmt(self, s: Stmt) -> None:
        if isinstance(s, VarDecl):
            self._var_decl(s)
        elif isinstance(s, Assign):
            self._assign(s)
        elif isinstance(s, If):
            if s.unsafe:
                self.unsafe_depth += 1
            for br in s.branches:
                self._condition(br.cond)
                self._block(br.body)
            if s.else_body is not None:
                self._block(s.else_body)
            if s.unsafe:
                self.unsafe_depth -= 1
        elif isinstance(s, While):
            self._condition(s.cond)
            self.loop_depth += 1
            self._block(s.body)
            self.loop_depth -= 1
        elif isinstance(s, For):
            self._for(s)
        elif isinstance(s, ForIn):
            self._for_in(s)
        elif isinstance(s, Return):
            self._return(s)
        elif isinstance(s, (Break, Continue)):
            if self.loop_depth == 0:
                word = "break" if isinstance(s, Break) else "continue"
                self._err(s, f"`{word}` can only be used inside a loop.")
        elif isinstance(s, Pass):
            pass
        elif isinstance(s, Match):
            self._match_stmt(s)
        elif isinstance(s, Yield):
            self._yield(s)
        elif isinstance(s, Defer):
            self._stmt(s.stmt)
        elif isinstance(s, Require):
            self._condition(s.cond)
        elif isinstance(s, Wrapping):
            self._block(s.body)
        elif isinstance(s, OverflowMode):
            pass
        elif isinstance(s, ExprStmt):
            self._whole_expr(s.expr)
            self._infer(s.expr, None)

    def _ref_place_ok(self, e: Expr) -> bool:
        """Can this expression be the source of a stored reference?"""
        if isinstance(e, BorrowExpr):
            return self._ref_place_ok(e.expr)
        if getattr(e, "view_ptr", False):
            return True
        return self._is_place_expr(e) and not isinstance(e, SliceExpr)

    def _lend_source_ok(self, e: Expr) -> bool:
        """A `lend` reference may come from a mutable place or from a `-> lend` result, not from a `read` view."""
        if isinstance(e, BorrowExpr):
            return e.mode == "lend"
        if getattr(e, "view_ptr", False):
            if getattr(e, "view_lend", False):
                return True
            self._err(e, "Cannot store a `read` reference as `lend`.",
                      "The source function returns `-> ref`, which is shared and read-only.")
            return False
        root = self._root_var(e)
        if root is not None and root.kind == "read":
            self._err(e, f"Cannot take `lend` from `{root.name}`: it is a `read` reference.",
                      "Mutating through a shared reference is not allowed.")
            return False
        return self._check_mutable(e, "lend")

    def _tie_root(self, e: Expr | None) -> str | None:
        """Variable the borrowed place is ultimately tied to."""
        if e is None:
            return None
        if isinstance(e, BorrowExpr):
            return self._tie_root(e.expr)
        marked = getattr(e, "tie_root", None)
        if marked and not isinstance(e, (Name, FieldAccess, IndexAccess, SliceExpr)):
            return marked
        if isinstance(e, (FieldAccess, IndexAccess, SliceExpr)):
            return self._tie_root(e.obj)
        if isinstance(e, Call) and e.callee in ("ptr_cast", "ptr_offset") and e.args:  # unsafe: `ptr_cast[*mut T](self.cell)[0]`
            return self._tie_root(e.args[0])
        if isinstance(e, Name):
            var = self._lookup(e.name)
            if var is not None and var.tie:
                return var.tie
            if var is not None and var.alias:
                return var.alias[0]
            return e.name
        return None

    def _ref_field_mode(self, place: Expr) -> str | None:
        if not isinstance(place, FieldAccess):
            return None
        oty = getattr(place.obj, "ty", None)
        si = self.structs.get(oty) if isinstance(oty, str) else None
        if si is None:
            return None
        return si.field_modes.get(place.field_name) or None

    def _crossed_lend_field(self, place: Expr) -> bool:
        """Does the path pass through a `lend` reference field to reach the pointee?"""
        e: Expr = place.obj if isinstance(place, FieldAccess) else place
        while isinstance(e, (FieldAccess, IndexAccess, SliceExpr)):
            if isinstance(e, FieldAccess):
                oty = getattr(e.obj, "ty", None)
                si = self.structs.get(oty) if isinstance(oty, str) else None
                if si is not None and si.field_modes.get(e.field_name) == "lend":
                    return True
            e = e.obj
        return False

    def _node_file(self, n: Node) -> str | None:
        own = getattr(n, "filename", None)
        if own is None and self.cur is not None and self.cur.decl is not None:
            own = getattr(self.cur.decl, "filename", None)
        return own

    @staticmethod
    def _var_key(s: VarDecl) -> tuple:
        return (getattr(s, "filename", None), s.line, s.col, s.name)

    def _note_change(self, root: VarInfo) -> None:
        """`root` is changed (assigned, lent, or a mutating method). A variable nobody changes is `fixed`."""
        if isinstance(root.origin, VarDecl):
            self.var_changes[self._var_key(root.origin)] = True

    def _bare_none(self, e: Expr) -> bool:
        return isinstance(e, Name) and e.name == "None" and self._lookup("None") is None

    def _none_key(self, s: VarDecl) -> tuple:
        inst = getattr(self.cur.decl, "inst_key", None) if self.cur is not None else None
        return ("none", self._node_file(s), s.line, s.col, s.name, inst)

    def _none_hint(self, var: VarInfo | None, ty: str | None) -> None:
        """`x = None` learns its type from `ty` when that is an `Optional[T]`."""
        key = getattr(var, "none_key", None)
        if key is not None and ty and ty != ERR and (generic_parts(ty) or ("",))[0] == "Optional":
            self.none_found.setdefault(key, ty)

    def _report_untyped_none(self) -> None:
        for key, s in self.none_pending.items():
            if key not in self.none_found:
                self._err(s.value, f"The type of `{s.name}` could not be inferred: `None` alone does not name it.",
                          f"Write the type: `{s.name}: Optional[i32] = None`, or assign `{s.name} = Valid(...)` later.")

    def _var_decl(self, s: VarDecl) -> None:
        # Generic instances share the source position: one change in any of them counts.
        self.var_changes.setdefault(self._var_key(s), False)
        declared = self._resolve(s.type_ref) if s.type_ref else None
        if declared is None and not s.ref_mode and self._bare_none(s.value):
            key = self._none_key(s)
            found = self.inferred.get(key)
            if found is None:  # type comes from a later use; until then `x` is unknown and reports nothing
                self.none_pending[key] = s
                s.ty = ERR
                info = VarInfo(s.name, ERR, s.mutable, "local")
                info.none_key = key  # type: ignore[attr-defined]
                self._declare(s.name, info, s)
                return
            base, args = generic_parts(found)  # type: ignore[misc]
            declared = self._instantiate_type(base, args, s)
        self._whole_expr(s.value)
        mode = s.ref_mode
        if isinstance(s.value, BorrowExpr):
            if mode and mode != s.value.mode:
                self._err(s.value, f"Reference mode `{mode}` does not match `{s.value.mode}`.",
                          f"Write `{mode} {unparse(s.value.expr)}` or change the annotation.")
            mode = s.value.mode
        vt = self._expr(s.value, declared)
        view = getattr(s.value, "view_ptr", False)
        if mode == "" and view and declared is None:
            mode = "lend" if getattr(s.value, "view_lend", False) else "read"
        if mode:
            if declared is not None and vt not in (ERR, declared):
                self._expect_type(declared, vt, s.value, widen=False)
            ty = declared or vt
            s.ty = ty
            if is_slice_type(ty):
                self._err(s, f"A slice is already a view: write `{s.name} = ...` without `{mode}`.")
            elif ty != ERR:
                if not self._ref_place_ok(s.value):
                    self._err(s.value, "A reference must be bound to a variable, field, index, or another reference.",
                              "Assign the value to a variable first, then borrow that variable.")
                elif mode == "lend":
                    self._lend_source_ok(s.value)
                root = self._tie_root(s.value)
                s.ref_mode = mode
                s.ref_root = root
                self._declare(s.name, VarInfo(s.name, ty, s.mutable, mode, ref_slot=True, tie=root), s)
            else:
                self._declare(s.name, VarInfo(s.name, ERR, s.mutable, mode, ref_slot=True), s)
            return
        if declared is not None:
            self._expect_type(declared, vt, s.value)
            ty = declared
        else:
            ty = vt
        self._no_implicit_copy(s.value, ty)
        s.ty = ty
        self._declare(s.name, VarInfo(s.name, ty, s.mutable, "local"), s)

    def _block_expr(self, e: BlockExpr, expected: str | None) -> str:
        """`if c then a else b` / `match x:` + `Arm => v`: arm value types must be identical."""
        frame: dict = {"expected": expected, "ty": None}
        self.yields.append(frame)
        self._stmt(e.stmt)
        self.yields.pop()
        if frame.get("view_ptr"):
            e.view_ptr = True  # type: ignore[attr-defined]
            e.is_view = True
            e.view_lend = bool(frame.get("view_lend"))  # type: ignore[attr-defined]
            e.tie_root = frame.get("tie_root")  # type: ignore[attr-defined]
        return frame["ty"] or ERR

    def _yield(self, s: Yield) -> None:
        frame = self.yields[-1]
        self._whole_expr(s.value)
        vt = self._expr(s.value, frame["ty"] or frame["expected"])
        if vt == ERR:
            return
        if frame["ty"] is None:
            frame["ty"] = vt
        else:
            self._expect_type(frame["ty"], vt, s.value)
        ptr = bool(getattr(s.value, "view_ptr", False))
        if "view_ptr" not in frame:
            frame["view_ptr"] = ptr
            frame["view_lend"] = bool(getattr(s.value, "view_lend", False))
            frame["tie_root"] = getattr(s.value, "tie_root", None) or self._tie_root(s.value)
        elif bool(frame["view_ptr"]) != ptr:
            self._err(s.value, "Every arm must be a reference, or every arm must be an owned value.")
            frame["view_ptr"] = False
        elif frame["view_ptr"]:
            tie = getattr(s.value, "tie_root", None) or self._tie_root(s.value)
            if frame.get("tie_root") != tie:
                self._err(s.value, "Reference arms must be tied to the same value.")
                frame["view_ptr"] = False
            frame["view_lend"] = frame.get("view_lend") and getattr(s.value, "view_lend", False)
        if not ptr:
            self._no_implicit_copy(s.value, vt)

    def _condition(self, e: Expr) -> None:
        t = self._expr(e, "bool")
        if t not in (ERR, "bool"):
            self._err(e, f"Condition must be `bool`, found `{t}`.", "Use a comparison, e.g. `x != 0`.")

    def _for(self, s: For) -> None:
        if _is_const_expr(s.start) and not _is_const_expr(s.end):
            et = self._expr(s.end)
            st = self._expr(s.start, et if et in INTS else None)
        else:
            st = self._expr(s.start)
            et = self._expr(s.end, st if st in INTS else None)
        ty = ERR
        if ERR not in (st, et):
            if st not in INTS:
                self._err(s.start, f"`for` range must be an integer, found `{st}`.")
            elif st != et:
                self._err(s.end, f"Both ends of range must have the same type: `{st}` and `{et}`.")
            else:
                ty = st
        if s.step is not None:
            sv: int | None = None
            sx = s.step
            if isinstance(sx, IntLit):
                sv = sx.value
            elif isinstance(sx, Unary) and sx.op == "-" and isinstance(sx.operand, IntLit):
                sv = -sx.operand.value
            if sv is None:
                self._err(sx, "`step` must be an integer literal.", "Write e.g. `step 2` or `step -1`.")
            elif sv == 0:
                self._err(sx, "`step` cannot be zero.", "Use a non-zero step.")
            else:
                s.step_value = sv
                self._expr(sx, ty if ty in INTS else None)
                if sv < 0 and ty in UNSIGNED_INTS:
                    self._err(sx, f"Negative `step` cannot be used with unsigned type `{ty}`.",
                              "Use a signed integer type for descending loops.")
                elif ty in INT_RANGES and abs(sv) > INT_RANGES[ty][1]:
                    self._err(sx, f"`step` {sv} does not fit in `{ty}`.", "Use a smaller step.")
        s.var_ty = ty
        self.scopes.append({})
        counter = VarInfo(s.var, ty, False, "loop")
        lo, hi = self._eval_const(s.start), self._eval_const(s.end)
        if ty in INTS and isinstance(lo, int) and isinstance(hi, int) and not isinstance(lo, bool):
            counter.lit_range = (min(lo, hi), max(lo, hi))
            s.const_bounds = (lo, hi)  # type: ignore[attr-defined]  # for counters.py
        self._declare(s.var, counter, s)
        self.loop_depth += 1
        self._block(s.body)
        self.loop_depth -= 1
        self.scopes.pop()

    def _for_iterator(self, s: ForIn) -> None:
        """`for x in it:` over a type with `next(self: lend T) -> Optional[X]` is rewritten into
        `while true: match it.next(): Valid(x): body; _: break` (the statement is replaced in its block)."""
        if s.index_var is not None:
            self._err(s, "An index variable cannot be used with an iterator.", "Write `for x in it:`.")
            return
        from .ast_nodes import Binding, Branch, MatchArm  # local: keep import list of this module unchanged
        from .ast_nodes import Match as MatchStmt

        def at(n):
            n.line, n.col, n.length = s.line, s.col, s.length
            n.filename = getattr(s, "filename", None)
            return n

        pre: list[Stmt] = []
        if _place_path(s.iterable) is not None:
            it = s.iterable
        else:
            self.iter_counter = getattr(self, "iter_counter", 0) + 1
            tmp = f"__iter{self.iter_counter}"
            pre.append(at(VarDecl(tmp, True, None, s.iterable)))
            it = at(Name(tmp))
        call = at(MethodCall(it, "next", []))
        arm = at(MatchArm("Valid", None, [at(Binding(s.var))], s.body, True))
        wild = at(MatchArm(None, None, [], [at(Break())], False))
        loop = at(While(at(BoolLit(True)), [at(MatchStmt(call, "", [arm, wild]))]))
        node = at(If([at(Branch(at(BoolLit(True)), pre + [loop]))], None))
        s.desugared = node  # type: ignore[attr-defined]
        self._stmt(node)

    def _loop_key(self, s: ForIn) -> tuple:
        inst = getattr(self.cur.decl, "inst_key", None) if self.cur is not None else None
        return ("loop", self._node_file(s), s.line, s.col, s.var, inst)

    def _infer_loop_lend(self, root: VarInfo) -> bool:
        """The body of `for x in xs:` changes `x`: record that `x` must lend each element.
        check_program then re-checks the program with `x` as a `lend` reference into `xs`."""
        s = root.origin
        if not isinstance(s, ForIn) or root.name != s.var or s.count or s.mutable or root.kind not in ("read", "loop"):
            return False
        it_ty = getattr(s.iterable, "ty", None)
        if not isinstance(it_ty, str) or _place_path(s.iterable) is None:
            return False
        if not (is_array_type(it_ty) or is_slice_type(it_ty) or heap_kind(it_ty) == "List"):
            return False
        self.mode_upgrades[self._loop_key(s)] = "lend"
        return True

    def _for_in(self, s: ForIn) -> None:
        if self.inferred.get(self._loop_key(s)) == "lend":
            s.mutable = True  # the body changes the loop variable: it lends each element
        it_ty = self._expr(s.iterable)
        ty = ERR
        by_ref = False
        if it_ty != ERR:
            elem_ty = ERR
            if it_ty in INTS:  # `for i in N:` == `for i in 0..N:`
                if s.index_var is not None:
                    self._err(s, "An index variable cannot be used when counting over an integer.",
                              "Write `for i in n:`.")
                else:
                    s.count = True
                    elem_ty = it_ty
            elif is_array_type(it_ty):
                _, elem_ty = array_info(it_ty)
            elif is_slice_type(it_ty):
                elem_ty = slice_elem_type(it_ty)
            elif heap_kind(it_ty) == "List":
                elem_ty = heap_inner(it_ty)
            elif it_ty == "str":
                elem_ty = "u8"
            elif (it_ty in self.structs or it_ty in self.enums) and (
                    f"{it_ty}.next" in self.funcs or self._method_template_info(it_ty, "next", s) is not None):
                self._for_iterator(s)  # user-defined iterator: `fn T.next(self: lend T) -> Optional[X]`
                return
            else:
                self._err(s.iterable, f"Cannot iterate over type `{it_ty}` with `for .. in`.",
                          "Can iterate over integers (`for i in n:`), arrays, slices, lists and strings.")
            if elem_ty != ERR:
                ty = elem_ty
                by_ref = not s.count and (s.mutable or elem_ty not in PRIMS)
                if s.mutable and it_ty != "str" and not s.count:
                    if _place_path(s.iterable) is not None:
                        self._check_mutable(s.iterable, "lend")
                    else:
                        self._err(s.iterable, "Changing the loop variable needs a variable or a field to loop over.",
                                  "Assign the value to a variable first.")
        s.elem_ty = ty
        s.by_ref = by_ref
        self.scopes.append({})
        if by_ref:
            path = self._path(s.iterable)
            alias = path + ("[*]",) if path is not None else None
            info = (VarInfo(s.var, ty, True, "lend", alias, True) if s.mutable
                    else VarInfo(s.var, ty, False, "read", alias, True))
        else:
            info = VarInfo(s.var, ty, False, "loop")
        self._declare(s.var, info, s)
        if s.index_var is not None:
            self._declare(s.index_var, VarInfo(s.index_var, "usize", False, "loop"), s)
        self.loop_depth += 1
        self._block(s.body)
        self.loop_depth -= 1
        self.scopes.pop()

    def _return(self, s: Return) -> None:
        assert self.cur is not None
        ret = self.cur.ret
        if s.value is None:
            if ret not in (VOID, ERR):
                self._err(s, f"Function `{self.cur.decl.name}` must return `{ret}`.", "Write `return value`.")
            return
        if ret == VOID:
            self._expr_any(s.value)
            self._err(s, f"Function `{self.cur.decl.name}` does not return a value, but `return` carries a value.",
                      f"Add return type: `-> {s.value.ty if s.value.ty not in (None, ERR, VOID) else 'type'}`.")
            return
        self._whole_expr(s.value)
        vt = self._expr(s.value, ret)
        self._expect_type(ret, vt, s.value)
        if self.cur.ret_view:
            self._check_view_return(s.value)
            return
        if self._moves(ret) and isinstance(s.value, Name):
            # `return x`: if x is local owner, ownership is moved to caller (implicit move); otherwise would be copy.
            var = self._lookup(s.value.name)
            if var is not None and var.kind in ("local", "consume"):
                s.value.is_move = True
            else:
                self._no_implicit_copy(s.value, ret)
        else:
            self._no_implicit_copy(s.value, ret)

    def _check_view_return(self, e: Expr) -> None:
        """Returned place must derive from the one `read`/`lend` parameter this function is tied to."""
        assert self.cur is not None
        word = "lend" if self.cur.ret_lend else "ref"
        if not self._ref_place_ok(e):
            self._err(e, f"`{word}` return must be a place inside a parameter, not `{unparse(e)}`.",
                      "Return a parameter, a field, an index, or a reference derived from one.")
            return
        origin = self._tie_root(e)
        params = {p.name: p for p in self.cur.params}
        if origin not in params:
            self._err(e, f"`{word}` return must derive from a parameter; `{unparse(e)}` does not.",
                      "A reference to a local value would dangle after the function returns.")
            return
        param = params[origin]
        if param.mode not in ("read", "lend"):
            self._err(e, f"`{word}` return cannot derive from `{origin}`: that parameter is not a `read` or `lend` reference.",
                      f"Make it `{origin}: read {param.ty}` or `{origin}: lend {param.ty}`. A by-value or `consume` parameter dies when the function returns.")
            return
        if self.cur.ret_lend and param.mode != "lend":
            self._err(e, f"`-> lend` must derive from a `lend` parameter; `{origin}` is `read`.",
                      f"Change the parameter to `{origin}: lend {param.ty}`, or return `-> ref`.")
            return
        expected = self.cur.ret_origin or (self.cur.decl.ret_tied if self.cur.decl else None)
        if expected is None:
            self.cur.ret_origin = origin
        elif expected != origin:
            self._err(e, f"`{word}` return is tied to `{expected}`, but `{unparse(e)}` derives from `{origin}`.",
                      f"Return a place inside `{expected}`, or write `tied to {origin}`.")

    def _is_new_binding(self, s: Stmt) -> bool:
        """`x = v` where `x` is not yet a variable declares it."""
        return isinstance(s, Assign) and s.op == "=" and isinstance(s.target, Name) \
            and self._lookup(s.target.name) is None

    def _is_existing_binding(self, s: Stmt) -> bool:
        """Bare `x = v` parsed as `VarDecl` when `x` resolves in scope (e.g. an imported constant/static)."""
        return (isinstance(s, VarDecl) and s.type_ref is None and not s.ref_mode
                and not hasattr(s, "fixed_at") and self._lookup(s.name) is not None)

    @staticmethod
    def _decl_from_assign(s: Assign) -> VarDecl:
        t = s.target
        d = VarDecl(t.name, True, None, s.value, line=s.line, col=s.col, length=s.length)  # type: ignore[call-arg]
        d.filename = getattr(s, "filename", None)  # type: ignore[attr-defined]
        d.is_soa = isinstance(s.value, SoaExpr)
        d.name_at = (t.line, t.col)  # type: ignore[attr-defined]
        op_at = getattr(s, "op_at", None)
        if op_at is not None:
            d.op_at = op_at  # type: ignore[attr-defined]
        return d

    @staticmethod
    def _assign_from_decl(s: VarDecl) -> Assign:
        nline, ncol = getattr(s, "name_at", (s.line, s.col))
        target = Name(s.name, line=nline, col=ncol, length=len(s.name))
        target.filename = getattr(s, "filename", None)  # type: ignore[attr-defined]
        a = Assign(target, "=", s.value, line=s.line, col=s.col, length=s.length)
        a.filename = getattr(s, "filename", None)  # type: ignore[attr-defined]
        op_at = getattr(s, "op_at", None)
        if op_at is not None:
            a.op_at = op_at  # type: ignore[attr-defined]
        return a

    def _assign_to_unknown(self, s: Assign) -> bool:
        """`x = 5` with no `x` in a place where a declaration cannot stand (e.g. after `defer`)."""
        t = s.target
        if s.op != "=" or not isinstance(t, Name) or self._lookup(t.name) is not None \
                or self._visible_func(t.name) is not None or t.name in SHORT_CTORS:
            return False
        visible = [n for scope in self.scopes for n in scope]
        near = friendly.nearest(t.name, visible)
        fixes: list[Fix] = []
        fname = getattr(s, "filename", None)
        if near:
            fixes.append(friendly.rename_fix(t.line, t.col, t.name, near, fname))
        self._err(t, f"`{t.name}` is not defined.",
                  f"Declare `{t.name}` on its own line first." + (f" Or did you mean `{near}`?" if near else ""),
                  fixes=fixes)
        self._expr_any(s.value)
        return True

    def _assign(self, s: Assign) -> None:
        if self._assign_to_unknown(s):
            return
        if s.op == "=" and isinstance(s.target, Name):
            pending = self._lookup(s.target.name)
            if getattr(pending, "none_key", None) is not None:
                if not self._bare_none(s.value):
                    self._none_hint(pending, self._expr(s.value))
                return
        tt = self._expr(s.target)
        if isinstance(s.target, (Call, MethodCall)):  # `g.value() += 1`: through a returned `lend T`
            if tt != ERR and not getattr(s.target, "view_lend", False):
                self._err(s.target, f"`{unparse(s.target)}` is a value, not a place.",
                          "Only a call that returns `lend T` can be assigned to; assign to a variable or field.")
                return
            self._whole_expr(s.value)
            vt = self._expr(s.value, tt if tt != ERR else None)
            if ERR not in (tt, vt):
                self._expect_type(tt, vt, s.value)
                if s.op != "=" and int_base(tt) not in NUMERIC:
                    self._err(s, f"`{s.op}` needs a number, found `{tt}`.")
            return
        if s.op == "=" and isinstance(s.target, Name):
            root = self._root_var(s.target)
            if root is not None and root.ref_slot:
                if not root.mutable:
                    self._err(s.target, f"Cannot rebind `{root.name}`: the reference binding is `fixed`.",
                              f"Delete `fixed` from the declaration of `{root.name}` to retie it.",
                              fixes=self._place_fixes(root, "assign"))
                self._note_change(root)
                self._whole_expr(s.value)
                vt = self._expr(s.value, tt if tt != ERR else None)
                if ERR not in (tt, vt):
                    self._expect_type(tt, vt, s.value)
                if not self._ref_place_ok(s.value):
                    self._err(s.value, "A reference can only be retied to a place or another reference.")
                elif root.kind == "lend":
                    self._lend_source_ok(s.value)
                s.rebind = True
                s.ref_mode = root.kind
                s.ref_root = self._tie_root(s.value)
                root.tie = s.ref_root
                return
        fmode = self._ref_field_mode(s.target) if s.op == "=" else None
        if fmode:
            self._check_mutable(s.target, "assign")
            self._whole_expr(s.value)
            vt = self._expr(s.value, tt if tt != ERR else None)
            if ERR not in (tt, vt):
                self._expect_type(tt, vt, s.value)
            if not self._ref_place_ok(s.value):
                self._err(s.value, f"Reference field expects a place, not `{unparse(s.value)}`.")
            elif fmode == "lend":
                self._lend_source_ok(s.value)
            s.rebind = True
            s.ref_mode = fmode
            s.ref_root = self._tie_root(s.value)
            return
        self._check_mutable(s.target, "assign")
        if s.op == "=":
            self._whole_expr(s.value)
        vt = self._expr(s.value, tt if tt != ERR else None)
        if ERR in (tt, vt):
            return
        if s.op == "=":
            self._expect_type(tt, vt, s.value)
            self._no_implicit_copy(s.value, tt)
            return
        base_tt = bounded_int_info(tt)[0] if is_bounded_int(tt) else tt
        base_vt = bounded_int_info(vt)[0] if is_bounded_int(vt) else vt
        if s.op in ("+=", "-=", "*=", "/="):
            if base_tt not in NUMERIC:
                self._err(s, f"`{s.op}` can only be used with numbers, found `{tt}`.")
            else:
                self._expect_type(tt, vt, s.value)
        elif s.op in ("%=", "&=", "|=", "^="):
            if base_tt not in INTS:
                self._err(s, f"`{s.op}` can only be used with integers, found `{tt}`.")
            else:
                self._expect_type(tt, vt, s.value)
        elif s.op in ("<<=", ">>="):
            if base_tt not in INTS:
                self._err(s, f"`{s.op}` left side must be an integer, found `{tt}`.")
            elif base_vt not in INTS:
                self._err(s.value, f"`{s.op}` right side must be an integer, found `{vt}`.")
        else:
            self._expect_type(tt, vt, s.value)

    def _path(self, e: Expr) -> tuple[str, ...] | None:
        """Access path for alias checking: `match lend` bindings are aliases into scrutinee."""
        p = _place_path(e)
        if p is None:
            return None
        var = self._lookup(p[0])
        if var is not None and var.tie:
            p = (var.tie,) + p[1:]
            var = self._lookup(p[0])
        if var is not None and var.alias is not None:
            return var.alias + p[1:]
        return p

    def _variant_owners(self, name: str) -> list[str]:
        """Enums that have a variant named `name` (hint for bare variant name)."""
        out = [n for n, info in self.enums.items() if name in info.variants]
        out += [n for n, d in self.generic_enums.items() if any(v.name == name for v in d.variants)]
        return out

    # -- mutability -----------------------------------------
    def _root_var(self, e: Expr) -> VarInfo | None:
        while isinstance(e, (FieldAccess, IndexAccess, SliceExpr)):
            e = e.obj
        return self._lookup(e.name) if isinstance(e, Name) else None

    def _through_read_field(self, place: Expr) -> bool:
        """Does place expression pass through a `read` reference field?"""
        e = place
        while isinstance(e, (FieldAccess, IndexAccess, SliceExpr)):
            if isinstance(e, FieldAccess):
                oty = getattr(e.obj, "ty", None)
                si = self.structs.get(oty) if isinstance(oty, str) else None
                if si is not None and si.field_modes.get(e.field_name) == "read":
                    return True
            e = e.obj
        return False

    @staticmethod
    def _shared_kind(place: Expr) -> str:
        """`Shared` or `Arc`: the kind of the shared value `place` goes through."""
        e = place
        while isinstance(e, (FieldAccess, IndexAccess, SliceExpr)):
            kind = heap_kind(getattr(e.obj, "ty", None) or "") if isinstance(e, FieldAccess) else None
            if kind in SHARED_KINDS:
                return kind  # type: ignore[return-value]
            e = e.obj
        return "Shared"

    def _check_mutable(self, place: Expr, what: str, method: str = "") -> bool:
        """Is `place` mutable? what: "assign" | "lend" | "method"."""
        shared = self._through_shared(place)
        if shared is not None:
            self._err(place, f"`{unparse(place)}` cannot be changed: `{shared}` is a `{self._shared_kind(place)}` value, which is read-only.",
                      "Other owners may see the same value. Clone the inner value to change a private copy: "
                      f"`mine = {shared}.value.clone()`.")
            return False
        captured = self._captured_place(place)
        if captured is not None and self._capture_mode(captured) != "lend":
            if self._infer_capture(captured):
                return True  # re-checked with `captured` borrowed as `lend` by the closure
            if self.cur is not None and self.cur.params and self.cur.params[0].ty in self.owning_closures:
                self._err(place, f"A `Fn` closure cannot change `{captured}`: it owns its own copy, "
                                 "so the change would not be seen outside.",
                          f"Pass `{captured}` to the lambda as a `lend` parameter instead.")
            else:
                self._err(place, f"A closure cannot change `{captured}` here.",
                          f"Pass `{captured}` to the lambda as a `lend` parameter, or change it outside the lambda.")
            return False
        e: Expr = place
        while isinstance(e, (FieldAccess, IndexAccess, SliceExpr)):  # `p[i]`, `p[i].field`: mutability of pointer inspected
            if isinstance(e, IndexAccess):
                pty = getattr(e.obj, "ty", None)
                if isinstance(pty, str) and is_slice_type(pty) and not isinstance(e.obj, Name):
                    self._err(place, f"`{unparse(place)}` cannot be changed: a slice stored in a field is a read-only view.",
                              "Change the elements through the owner, or pass the slice as a `lend []T` parameter.",
                              rule="immutable-place", details={"name": unparse(e.obj)})
                    return False
                if isinstance(pty, str) and is_slice_type(pty) and isinstance(e.obj, Name):
                    var = self._lookup(e.obj.name)
                    if var is not None and var.kind == "local":
                        self._err(place, f"`{unparse(place)}` cannot be changed: `{var.name}` is a slice stored in a "
                                         "variable, a read-only view.",
                                  "Change the elements through the owner, or pass the slice as a `lend []T` parameter.",
                                  rule="immutable-place", details={"name": var.name})
                        return False
                if isinstance(pty, str) and is_ptr_type(pty):
                    if ptr_is_mut(pty):
                        return True
                    self._err(place, f"`{unparse(place)}` is immutable: `{pty}` is a read-only pointer.",
                              f"Use `*mut {ptr_elem(pty)}` to write.")
                    return False
            e = e.obj
        root = self._root_var(place)
        if root is None:
            if _place_path(place) is None:
                self._err(place, "Expected a variable or field here (`x` or `x.field`).")
            return False  # undefined variable already reported
        if isinstance(place, IndexAccess) and getattr(place.obj, "ty", None) == "str":
            if what == "assign":
                self._err(place, "Cannot assign to string characters: string is immutable.",
                          "Strings are immutable; create a new string or use u8 array.")
            else:
                self._err(place, "Cannot `lend` string character: string is immutable.",
                          "Strings are immutable; use u8 array.")
            return False
        if self._through_read_field(place):
            self._err(place, f"`{unparse(place)}` is immutable: read-only access through `read` reference field.",
                      "Make the field `lend` or mutate through the owner.")
            return False
        if root.ref_slot and isinstance(place, Name):
            if what == "assign":
                if not root.mutable:
                    self._err(place, f"Cannot rebind `{root.name}`: the reference binding is `fixed`.",
                              f"Delete `fixed` from the declaration of `{root.name}` to retie it.",
                              fixes=self._place_fixes(root, "assign"))
                    return False
                self._note_change(root)
                return True
            if root.kind == "read":
                self._err(place, f"`{unparse(place)}` cannot be `lend`ed: `{root.name}` is a `read` reference.",
                          "A shared reference cannot grant mutable access.")
                return False
            return True
        if root.ref_slot and root.kind == "read":
            self._err(place, f"`{unparse(place)}` is immutable: `{root.name}` is a `read` reference.",
                      "Use `lend` to mutate through a reference.")
            return False
        field_mode = self._ref_field_mode(place)
        if field_mode == "lend" and what in ("lend", "method"):
            return True
        if self._crossed_lend_field(place):
            return True
        if root.ref_slot and root.kind == "lend":
            return True
        if root.mutable:
            self._note_change(root)
            return True
        if root.kind == "read" and self._infer_mode(root, "lend"):
            return True
        if root.kind == "val" and is_slice_type(root.ty) and self._infer_mode(root, "lend"):
            return True
        if self._infer_loop_lend(root):
            return True
        if what == "assign" and root.kind in ("val", "read") and is_slice_type(root.ty):
            self._err(place, f"Cannot assign to element of `{unparse(place)}`: `{root.name}` is a read-only slice.",
                      "Elements of read-only slice cannot be modified; make parameter `lend []T`.")
            return False
        temp_elem = (root.kind in ("read", "loop") and isinstance(root.origin, ForIn) and not root.origin.count
                     and root.name == root.origin.var and getattr(root.origin.iterable, "ty", None) != "str")
        if temp_elem:
            reason = f"`{root.name}` is an element of a temporary value"
        elif root.kind == "loop" and isinstance(root.origin, ForIn) and getattr(root.origin.iterable, "ty", None) == "str":
            reason = f"`{root.name}` is a byte of a `str`, and a `str` cannot be changed"
        elif root.kind in ("val", "read") and is_slice_type(root.ty):
            reason = f"`{root.name}` is a read-only slice"
        else:
            reason = {
                "local": f"`{root.name}` is declared `fixed`",
                "val": f"`{root.name}` is a value parameter (immutable)",
                "read": f"`{root.name}` is a `read` parameter (read-only)",
                "consume": f"`{root.name}` is an owned parameter that cannot be changed",
                "lend": f"`{root.name}` is immutable",
                "loop": f"`{root.name}` is a loop counter (it cannot be changed)",
                "const": f"`{root.name}` is a constant (const)",
            }[root.kind]
        text = unparse(place)
        is_index = isinstance(place, IndexAccess)
        is_field = isinstance(place, FieldAccess)
        what_str = "element of" if is_index else ("field of" if is_field else "variable")
        if what == "assign":
            msg = f"Cannot assign to {what_str} `{text}`: {reason}."
        elif what == "lend":
            msg = f"`{text}` cannot be `lend`ed: {reason}."
        else:
            msg = f"`{method}` changes `{root.name}`, but {reason}."
        if temp_elem:
            hint = f"Loop over a variable or a field (not a temporary value) to change its elements through `{root.name}`."
        elif root.kind in ("val", "read") and is_slice_type(root.ty):
            hint = "Read-only slice cannot be passed to `lend` parameter; make parameter `lend []T`."
        else:
            hint = {
                "local": f"Delete `fixed` from the declaration of `{root.name}`.",
                "val": f"To mutate, make parameter `{root.name}: lend Type`.",
                "read": f"To mutate, make parameter `{root.name}: lend Type`.",
                "consume": f"Make a local copy to change: `mine = copy {root.name}`.",
                "lend": "This is a mutating reference; it should have been directly mutable.",
                "loop": f"Copy it into a new variable to change it: `j = {root.name}`.",
                "const": "Constants never change; copy it into a local variable to change it.",
            }[root.kind]
        rule = {"assign": "immutable-assign", "lend": "lend-immutable"}.get(what, "mutating-method")
        self._err(place, msg, hint, rule=rule,
                  labels=self._def_label(root, f"`{root.name}` is declared here"),
                  details={"name": root.name, "kind": root.kind},
                  fixes=self._place_fixes(root, what))
        return False

    # -- expressions ------------------------------------------------------
    def _expr(self, e: Expr, expected: str | None = None) -> str:
        """Value-producing expression: `void` is not accepted."""
        t = self._infer(e, expected)
        if t == VOID:
            self._err(e, "This call does not return a value, cannot be used as a value.")
            e.ty = ERR
            return ERR
        return t

    def _expr_any(self, e: Expr) -> str:
        return self._infer(e, None)

    def _infer(self, e: Expr, expected: str | None) -> str:
        t = self._infer_inner(e, expected)
        if getattr(e, "implicit", False) and isinstance(e, Cast):
            return e.ty  # the node became an implicit conversion while it was checked
        e.ty = t
        return t

    def _infer_inner(self, e: Expr, expected: str | None) -> str:
        if isinstance(e, IntLit):
            if expected and is_bounded_int(expected):
                base, lo, hi = bounded_int_info(expected)
                if lo <= e.value < hi:
                    return expected
                self._err(e, f"{e.value} is out of bounds for `{expected}` (range [{lo}, {hi})).")
                return expected
            ty = expected if (expected and expected in INTS) else "i32"
            min_val, max_val = INT_RANGES[ty]
            if e.value > max_val:
                self._err(e, f"{e.value} is too large for `{ty}`.",
                          "Use `i64` or an appropriate type for larger numbers." if ty == "i32" else None)
            return ty
        if isinstance(e, FloatLit):
            return expected if (expected and expected in FLOATS) else "f64"
        if isinstance(e, StrLit):
            return "str"
        if isinstance(e, CharLit):
            return "u8"
        if isinstance(e, BoolLit):
            return "bool"
        if isinstance(e, Name):
            return self._name(e, expected)
        if isinstance(e, FieldAccess):
            return self._field(e, expected)
        if isinstance(e, Cast):
            return self._cast(e)
        if isinstance(e, Unary):
            return self._unary(e, expected)
        if isinstance(e, Binary):
            return self._binary(e, expected)
        if isinstance(e, Call):
            return self._call(e, expected)
        if isinstance(e, MethodCall):
            return self._method_call(e, expected)
        if isinstance(e, Apply):
            return self._apply(e)
        if isinstance(e, StructLit):
            return self._struct_lit(e, expected)
        if isinstance(e, ArrayLit):
            return self._array_lit(e, expected)
        if isinstance(e, ArrayRepeatLit):
            return self._array_repeat_lit(e, expected)
        if isinstance(e, IndexAccess):
            return self._index_access(e)
        if isinstance(e, SliceExpr):
            return self._slice_expr(e)
        if isinstance(e, Try):
            return self._try(e)
        if isinstance(e, CopyExpr):
            return self._copy_expr(e, expected)
        if isinstance(e, BorrowExpr):
            return self._borrow_expr(e, expected)
        if isinstance(e, SoaExpr):
            return self._soa_expr(e)
        if isinstance(e, BlockExpr):
            return self._block_expr(e, expected)
        if isinstance(e, FormatStr):
            return self._format_str(e)
        if isinstance(e, TypeApp):
            self._err(e, f"`{unparse(e)}` is a type, cannot be used as a value.",
                      "If constructing an enum variant write `Optional[i32].Valid(5)`, if calling generic function write `f[i32](...)`.")
            return ERR
        raise AssertionError(f"unexpected expression: {type(e).__name__}")

    def _format_str(self, e: FormatStr) -> str:
        for i, p in enumerate(e.parts):
            spec = getattr(p, "fmt_spec", None)
            if spec is not None:
                new = self._format_spec(p, spec)
                if new is not None:
                    e.parts[i] = new
                    self._expr(new)
                continue
            if isinstance(p, StrLit):
                p.ty = "str"
                continue
            pty = int_base(self._expr(p))
            if pty == ERR:
                continue
            bad = self._show_problem(pty)
            if bad is None:
                continue
            self._err(p, f"Type `{pty}` cannot be formatted in a string literal." if bad == pty else
                      f"Type `{pty}` cannot be formatted in a string literal: it contains `{bad}`.",
                      "Format a field instead, or define `fn to_string(self) -> string` in `impl`.")
        return "string"

    def _format_spec(self, p: Expr, spec: str) -> Expr | None:
        """`{x:spec}` -> calls of the Core `_fmt_*` helpers that build the text (None after an error)."""
        p.fmt_spec = None  # type: ignore[attr-defined]  # the value itself is formatted plainly below
        t = int_base(self._expr(p))
        if t == ERR:
            return None
        m = FORMAT_SPEC.match(spec)
        hint = ("A format is `[[fill]align][+][#][0][width][.precision][type]`: `{x:.2}` two decimals, `{n:>6}` "
                "right in 6 columns, `{n:<6}` left, `{n:^6}` centered, `{n:06}` zero-padded, `{n:+}` with a sign, "
                "`{n:x}` hex (`X`, `b`, `o`; `#` adds `0x`), `{x:e}` exponent.")

        def bad(why: str) -> None:
            self._err(p, f"Format `{spec}` cannot be used for `{t}`: {why}.", hint, rule="bad-format",
                      details={"format": spec, "type": t})

        if m is None:
            self._err(p, f"`{spec}` is not a format.", hint, rule="bad-format", details={"format": spec, "type": t})
            return None
        fill, align, plus, alt, zero = m["fill"], m["align"], m["sign"], m["alt"], m["zero"]
        width, prec, kind = m["width"], m["prec"], m["kind"]
        numeric, is_int, is_float = t in NUMERIC, t in INTS, t in FLOATS
        site = lambda n: _at(n, p)  # noqa: E731
        lit = lambda v: site(IntLit(v))  # noqa: E731
        flag = lambda v: site(BoolLit(bool(v)))  # noqa: E731
        if kind in ("x", "X", "b", "o"):
            if not is_int:
                bad(f"`{kind}` writes an integer in another base")
                return None
            base = {"x": 16, "X": 16, "b": 2, "o": 8}[kind]
            fn = "_fmt_radix_i" if t in SIGNED_INTS else "_fmt_radix_u"
            body: Expr = site(Call(fn, [p, lit(base), flag(kind == "X"), flag(alt)]))
        elif alt:
            bad("`#` adds a `0x`, `0b`, or `0o` prefix, so it needs `x`, `X`, `b`, or `o`")
            return None
        elif kind in ("e", "E"):
            if not numeric:
                bad("`e` writes a number with an exponent")
                return None
            arg = p if is_float else site(Cast("f64", p))
            body = site(Call("_fmt_exp", [arg, lit(int(prec) if prec else 6), flag(kind == "E")]))
        elif prec is not None:
            if not is_float:
                bad("a precision (`.2`) is the number of decimals of a float" + (
                    "; write `f64(x)` to show an integer with decimals" if is_int else ""))
                return None
            body = site(Call("_fmt_fixed", [p, lit(int(prec))]))
        elif kind == "d" and not is_int:
            bad("`d` writes an integer")
            return None
        else:
            body = site(FormatStr([p]))
        if (plus or zero) and not numeric:
            bad(f"`{'+' if plus else '0'}` is for numbers")
            return None
        if plus:
            body = site(Call("_fmt_plus", [body]))
        if width is not None and int(width) > 0:
            if zero and align:
                bad("`0` pads numbers with zeros and cannot be combined with an alignment")
                return None
            side = align or (">" if numeric else "<")
            body = site(Call("_fmt_pad", [body, lit(int(width)), site(StrLit(fill or " ")), lit(ord(side)),
                                          flag(zero)]))
        return body

    def _borrow_expr(self, e: BorrowExpr, expected: str | None) -> str:
        ty = self._expr(e.expr, expected)
        if not self._is_place_expr(e.expr):
            self._err(e.expr, f"`{e.mode}` needs a variable, field, or index.",
                      "Assign the value to a variable first.")
        elif e.mode == "lend":
            root = self._root_var(e.expr)
            if root is not None and root.kind == "read":
                self._err(e, f"Cannot `lend` `{unparse(e.expr)}`: it is a `read` reference.")
            elif getattr(e.expr, "view_ptr", False) and not getattr(e.expr, "view_lend", False):
                self._err(e, "Cannot `lend` a `read` reference.",
                          "Shared references cannot be upgraded to `lend`.")
            else:
                self._check_mutable(e.expr, "lend")
        e.is_view = True
        e.view_ptr = True  # type: ignore[attr-defined]
        e.view_lend = e.mode == "lend"  # type: ignore[attr-defined]
        e.tie_root = self._tie_root(e.expr)  # type: ignore[attr-defined]
        return ty

    def _copy_expr(self, e: CopyExpr, expected: str | None) -> str:
        """`copy x`: explicit copy. Heap-owning values cannot be copied (moved)."""
        ty = self._expr(e.expr, expected)
        if ty == ERR:
            return ERR
        handle = held_handle(ty, self.structs, self.enums) if ty != ERR else None
        if handle is not None and not self._drop(ty):
            self._err(e, f"`{ty}` holds the OS handle `{handle}`; it cannot be copied with `copy`.",
                      "A copy would be a second, unrelated object. Pass it as `read`/`lend`, or move it.",
                      rule="handle-copy", details={"value": unparse(e.expr), "handle": handle})
            return ERR
        if self._drop(ty):
            self._err(e, f"`{ty}` is a heap-owning value; cannot be copied with `copy`.",
                      "Assign value directly to transfer ownership; write a method for deep copy.")
            return ERR
        if is_slice_type(ty):
            self._err(e, "Slice cannot be copied.", "Slices are views only.")
            return ERR
        if not self._is_place_expr(e.expr):
            self._err(e, "`copy` applies to a variable, field, or array element.",
                      "`copy` is not needed for an already fresh value.")
        return ty

    def _soa_expr(self, e: SoaExpr) -> str:
        """`soa Array[T, N]`: array with struct element type; zeroed SoA layout."""
        ty = self._resolve(e.type_ref)
        if ty == ERR:
            return ERR
        if not is_array_type(ty):
            self._err(e, f"`soa` requires an array type (`Array[T, N]`), found `{ty}`.")
            return ERR
        _, elem = array_info(ty)
        if elem not in self.structs:
            self._err(e, f"`soa` is only meaningful for arrays with struct elements, found `{elem}`.",
                      "Flat numeric arrays are already contiguous in memory.")
            return ERR
        return ty

    def _array_lit(self, e: ArrayLit, expected: str | None) -> str:
        if not e.elements:
            if expected and is_array_type(expected):
                return expected
            self._err(e, "Cannot determine type of empty array; specify type explicitly.")
            return ERR
        if expected and is_slice_type(expected):  # `f(["a", "b"])` to a `[]string`: the elements take its type
            expected = f"[{len(e.elements)}]{slice_elem_type(expected)}"
        if expected and is_array_type(expected):
            exp_n, exp_elem = array_info(expected)
            if len(e.elements) != exp_n:
                self._err(e, f"Array size mismatch: expected {exp_n}, found {len(e.elements)}.")
            for el in e.elements:
                et = self._expr(el, exp_elem)
                self._expect_type(exp_elem, et, el)
                self._no_implicit_copy(el, et)  # `[a, b]` of heap owners moves `a` and `b` into the array
            return expected
        first_ty = self._expr(e.elements[0])
        self._no_implicit_copy(e.elements[0], first_ty)
        for el in e.elements[1:]:
            et = self._expr(el, first_ty)
            self._expect_type(first_ty, et, el)
            self._no_implicit_copy(el, et)
        return f"[{len(e.elements)}]{first_ty}"

    def _array_repeat_lit(self, e: ArrayRepeatLit, expected: str | None) -> str:
        count_val = self._eval_const(e.count)
        if count_val is None or not isinstance(count_val, int) or count_val < 0:
            self._err(e.count, "Array repeat count must be a positive constant integer.")
            return ERR
        if expected and is_array_type(expected):
            exp_n, exp_elem = array_info(expected)
            if count_val != exp_n:
                self._err(e, f"Array size mismatch: expected {exp_n}, found {count_val}.")
            vt = self._expr(e.value, exp_elem)
            self._expect_type(exp_elem, vt, e.value)
            self._repeat_moved(e, exp_elem, count_val)
            if count_val == 1:
                self._no_implicit_copy(e.value, vt)
            return expected
        vt = self._expr(e.value)
        self._repeat_moved(e, vt, count_val)
        if count_val == 1:
            self._no_implicit_copy(e.value, vt)
        return f"[{count_val}]{vt}"

    def _repeat_moved(self, e: ArrayRepeatLit, elem: str, count: int) -> None:
        """`[s; 3]` would put one owned value in three places."""
        if count > 1 and elem != ERR and self._moves(elem):
            self._err(e, f"`[x; {count}]` repeats one value, but `{elem}` is moved, not copied.",
                      f"Write each element (`[x.clone(), x.clone(), x]`), or build a `List[{elem}]` in a loop.",
                      rule="use-after-consume")

    def _index_access(self, e: IndexAccess) -> str:
        if getattr(e, "trusted", False):
            if self.unsafe_depth == 0:
                is_hot = self.cur is not None and getattr(self.cur.decl, "is_hot", False)
                self._err(e, "`trust` indexing can only be used inside an `unsafe:` block.",
                          ("`hot fn` is only a performance hint; it does not turn off bounds checks. "
                           if is_hot else "") + "Put the lines that use `trust` inside `unsafe:`.",
                          rule="unsafe-required")
        ot = self._expr(e.obj)
        it = self._expr(e.index)
        base_it = bounded_int_info(it)[0] if is_bounded_int(it) else it
        if it != ERR and base_it not in INTS:
            self._err(e.index, f"Array index must be an integer, found `{it}`.")
        if ot == ERR:
            return ERR
        if is_ptr_type(ot):
            if not self.unsafe_depth:
                self._err(e, f"`{unparse(e)}`: pointer dereference can only be performed in an `unsafe:` block.",
                          "Place the relevant lines inside `unsafe:`.")
            if ptr_elem(ot) == "void":
                self._err(e, "`*void` cannot be dereferenced.", "Convert to a concrete pointer first with `ptr_cast[*T](p)`.")
                return ERR
            return ptr_elem(ot)
        if is_array_type(ot):
            n, elem_ty = array_info(ot)
            c_idx = self._eval_const(e.index)
            if c_idx is not None and isinstance(c_idx, int):
                if c_idx < 0 or c_idx >= n:
                    self._err(e, f"Constant index {c_idx} out of bounds (array length {n}).",
                              "Index must be between 0 and length-1.")
            return elem_ty
        if is_slice_type(ot):
            return slice_elem_type(ot)
        if heap_kind(ot) == "List":
            return heap_inner(ot)  # a place inside the list: readable, changeable through a list that is not `fixed`, not movable
        if ot == "str":
            c_idx = self._eval_const(e.index)
            if c_idx is not None and isinstance(c_idx, int):
                if c_idx < 0:
                    self._err(e, f"Constant index {c_idx} cannot be negative.",
                              "Index must be 0 or greater.")
                elif isinstance(e.obj, StrLit):
                    slen = len(e.obj.value.encode("utf-8"))
                    if c_idx >= slen:
                        self._err(e, f"Constant index {c_idx} out of bounds (string length {slen}).",
                                  "Index must be between 0 and length-1.")
                elif isinstance(e.obj, Name):
                    ckey = getattr(e.obj, "const_key", None) or self._resolve_simple(e.obj.name)
                    c_val = self.consts[ckey].eval_val if ckey is not None and ckey in self.consts else None
                    if isinstance(c_val, str):
                        slen = len(c_val.encode("utf-8"))
                        if c_idx >= slen:
                            self._err(e, f"Constant index {c_idx} out of bounds (string length {slen}).",
                                      "Index must be between 0 and length-1.")
            return "u8"
        self._err(e.obj, f"Type `{ot}` cannot be indexed.")
        return ERR

    def _slice_expr(self, e: SliceExpr) -> str:
        ot = int_base(self._expr(e.obj))
        if ot == "string":  # `s[1..3]` on an owned string is a slice of its `str` view
            e.obj = _at(MethodCall(e.obj, "as_str", []), e.obj)
            ot = self._expr(e.obj)
        elem_ty = ERR
        if ot != ERR:
            if is_array_type(ot):
                _, elem_ty = array_info(ot)
            elif is_slice_type(ot):
                elem_ty = slice_elem_type(ot)
            elif heap_kind(ot) == "List":  # `xs[1..3]`: a view of the list's elements
                elem_ty = heap_inner(ot)
            elif ot == "str":  # a `str` view of bytes `start..end`; both ends must fall between characters
                for bound in (e.start, e.end):
                    if bound is not None:
                        bt = self._expr(bound)
                        if bt != ERR and bt not in INTS:
                            self._err(bound, f"Slice bound must be an integer, found `{bt}`.")
                return "str"
            else:
                self._err(e.obj, f"Type `{ot}` cannot be sliced.")
        if e.start is not None:
            st = self._expr(e.start)
            if st != ERR and st not in INTS:
                self._err(e.start, f"Slice start must be an integer, found `{st}`.")
        if e.end is not None:
            et = self._expr(e.end)
            if et != ERR and et not in INTS:
                self._err(e.end, f"Slice end must be an integer, found `{et}`.")
        if (not getattr(e, "in_call_arg", False) and ot != ERR and not self._is_place_expr(e.obj)
                and (is_array_type(ot) or self._drop(ot))):
            self._err(e, "A slice of a temporary value would outlive it.",
                      "Store the value in a variable first, then slice the variable.", rule="slice-position")
            return ERR
        return f"[]{elem_ty}"

    def _eval_const(self, e: Expr) -> int | float | None:
        if isinstance(e, IntLit):
            return e.value
        if isinstance(e, FloatLit):
            try:
                return float(e.text)
            except ValueError:
                return None
        if isinstance(e, Unary):
            val = self._eval_const(e.operand)
            if val is None:
                return None
            if e.op == "-":
                return -val
            if e.op == "~" and isinstance(val, int):
                return ~val
            return None
        if isinstance(e, Binary):
            l = self._eval_const(e.left)
            r = self._eval_const(e.right)
            if l is None or r is None:
                return None
            try:
                if e.op == "+":
                    return l + r
                if e.op == "-":
                    return l - r
                if e.op == "*":
                    return l * r
                if e.op == "/":
                    if r == 0:
                        return None
                    if isinstance(l, int) and isinstance(r, int):
                        return int(l / r)
                    return l / r
                if e.op == "%":
                    if r == 0 or not (isinstance(l, int) and isinstance(r, int)):
                        return None
                    return l - int(l / r) * r
                if isinstance(l, int) and isinstance(r, int):
                    if e.op == "&": return l & r
                    if e.op == "|": return l | r
                    if e.op == "^": return l ^ r
                    if e.op == "<<":
                        if r < 0 or r > 64: return None
                        return l << r
                    if e.op == ">>":
                        if r < 0 or r > 64: return None
                        return l >> r
            except Exception:
                return None
            return None
        if isinstance(e, Name):
            bound = self.tparams.get(e.name)
            if bound is not None and is_const_arg(bound):  # `[N]T` with `N: usize`
                return int(bound)
            key = self._resolve_simple(e.name)
            if key is not None and key in self.consts:
                return self.consts[key].eval_val
            return None
        if isinstance(e, Cast):
            val = self._eval_const(e.expr)
            if val is None:
                return None
            if e.target_type in INTS:
                return int(val)
            if e.target_type in FLOATS:
                return float(val)
        if isinstance(e, StrLit):
            return e.value
        if isinstance(e, CharLit):
            return e.value
        if isinstance(e, FieldAccess) and e.field_name == "len":
            obj_ty = self._expr(e.obj)
            if is_array_type(obj_ty):
                n, _ = array_info(obj_ty)
                return n
            if isinstance(e.obj, StrLit):
                return len(e.obj.value.encode("utf-8"))
            if isinstance(e.obj, Name):
                ckey = getattr(e.obj, "const_key", None) or self._resolve_simple(e.obj.name)
                c_val = self.consts[ckey].eval_val if ckey in self.consts else None
                if isinstance(c_val, str):
                    return len(c_val.encode("utf-8"))
        if isinstance(e, IndexAccess):
            c_idx = self._eval_const(e.index)
            if c_idx is not None and isinstance(c_idx, int):
                c_obj = self._eval_const(e.obj)
                if isinstance(c_obj, str):
                    encoded = c_obj.encode("utf-8")
                    if 0 <= c_idx < len(encoded):
                        return encoded[c_idx]
        return None

    def _enum_static(self, enum_name: str, method: str) -> bool:
        """`Color.from_int(2)`: an associated function of an enum, not a variant."""
        key = self._resolve_simple(enum_name) or enum_name
        info = self.enums.get(key)
        if info is None or method in info.variants:
            return False
        f = self.funcs.get(f"{key}.{method}")
        return f is not None and getattr(f.decl, "is_static", False)

    def _cast(self, e: Cast) -> str:
        target = TYPE_ALIASES.get(e.target_type, e.target_type)
        e.target_type = target
        base_target = bounded_int_info(target)[0] if is_bounded_int(target) else target
        if base_target not in NUMERIC:
            self._err(e, f"Unknown cast target type `{target}`.")
            return ERR
        vt = self._expr(e.expr)
        if vt == ERR:
            return ERR
        base_vt = bounded_int_info(vt)[0] if is_bounded_int(vt) else vt
        if vt in self.enums and base_target in INTS and f"{vt}.to_int" in self.funcs:
            inner = _at(MethodCall(e.expr, "to_int", []), e.expr)  # `i32(Color.Red)`: the variant's number
            e.expr = inner
            vt = base_vt = self._expr(inner)
        if base_vt not in NUMERIC:
            self._err(e.expr, f"Type `{vt}` cannot be converted to type `{target}`.",
                      "Explicit cast can only be performed between numeric types.")
            return ERR
        const_val = self._eval_const(e.expr)
        if const_val is not None:
            if base_target in INTS:
                ival = int(const_val)
                min_val, max_val = INT_RANGES[base_target]
                if not (min_val <= ival <= max_val):
                    self._err(e, f"Constant value {const_val} is out of range [{min_val}, {max_val}] for `{target}`.",
                              f"`{target}` range: {min_val} .. {max_val}.")
                    return ERR
        return target

    def _name(self, e: Name, expected: str | None = None) -> str:
        bound = self.tparams.get(e.name)
        if bound is not None and is_const_arg(bound) and self._lookup(e.name) is None:
            ty = self.const_types.get(e.name, "usize")  # `N` of `[N: usize]`: a constant in this instance
            _replace(e, _at(IntLit(int(bound)), e))
            e.ty = ty
            return ty
        var = self._lookup(e.name)
        self._none_hint(var, expected)
        if var is None and e.name == "null":  # null pointer: gets type from expected pointer type
            if expected is not None and is_ptr_type(expected):
                e.is_null = True  # type: ignore[attr-defined]
                return expected
            self._err(e, "Cannot determine pointer type for `null`.",
                      "Specify type explicitly: `p: *mut u8 = null` or compare `p == null` instead of `ptr_cast[*u8](null)`.")
            return ERR
        if var is not None and var.kind == "const":
            self._note_const(e)
        if var is not None and var.kind == "static":
            self._note_const(e)
            if not self.unsafe_depth:
                self._err(e, f"`{e.name}` is a `static`: reading or writing it needs `unsafe:`.",
                          "Another thread may use the same global at the same time; put the access inside "
                          "`unsafe:`, or keep the value in a local and pass it along.", rule="unsafe-required")
        if var is None and e.name.startswith("__lambda_"):
            inst = self._generic_lambda(e.name, e)
            if inst is not None:  # a lambda inside a generic function, for this instance
                e.func_key = inst.key  # type: ignore[attr-defined]
                return self._lambda_value(e, inst, expected)
        seen_fn = self._visible_func(e.name)
        gkey = self._resolve_simple(e.name)
        if var is None and seen_fn is not None and (gkey is None or gkey not in self.generic_funcs):
            if self._is_lambda(seen_fn):
                return self._lambda_value(e, seen_fn, expected)
            e.func_key = seen_fn.key  # type: ignore[attr-defined]
            return self._func_ref(e, seen_fn)
        if var is None and e.name in SHORT_CTORS and SHORT_CTORS[e.name] in self.generic_enums:  # None
            return self._variant_ctor(e, (SHORT_CTORS[e.name], None), e.name, None, expected)
        if var is None:
            owners = self._variant_owners(e.name)
            if owners:
                self._err(e, f"`{e.name}` is a variant name; qualifier is required.",
                          f"Write `{owners[0]}.{e.name}` (variants are qualified by enum name).")
                return ERR
            visible = [n for scope in self.scopes for n in scope] + [k for k in self.consts if "::" not in k]                 + list(self.mod_binds.get(self.scope_slug, {}))
            fixes: list[Fix] = []
            near = friendly.nearest(e.name, visible + ["true", "false", "None", "null"], friendly.NAME_SYNONYMS)
            stem = e.name.lower()
            binds = self.mod_binds.get(self.scope_slug, {})
            if stem in friendly.std_modules() and stem not in binds and e.name not in visible:
                fname = getattr(e, "filename", None)
                self._err(e, f"`{e.name}` is not defined.", f"`std.{stem}` is a module: add `import std.{stem}`.",
                          fixes=[Fix(f"Import `std.{stem}`", "safe",
                                     [Edit(1, 1, 1, 1, f"import std.{stem}\n", fname)]
                                     + ([Edit(e.line, e.col, e.line, e.col + len(e.name), stem, fname)]
                                        if e.name != stem else []))])
                return ERR
            if e.name in self.free_funcs:
                hint = f"`{e.name}` is a function; write `{e.name}(...)` to call."
            elif near:
                hint = f"Did you mean: `{near}`?"
                sure = friendly.NAME_SYNONYMS.get(e.name) == near
                fixes = [friendly.rename_fix(e.line, e.col, e.name, near, getattr(e, "filename", None),
                                             "safe" if sure else "likely")]
            else:
                hint = f"Define with `{e.name} = ...` first."
            self._err(e, f"`{e.name}` is not defined.", hint, fixes=fixes)
            return ERR
        e.is_ref = var.kind in ("lend", "read") and not is_slice_type(var.ty)
        return var.ty

    def _unknown_call_help(self, e: Call) -> tuple[str, list[Fix]]:
        """`sqrt(x)` without `math.`, `len(xs)`, `Some(3)`, `prnt(x)`: the hint and the edit."""
        fname = getattr(e, "filename", None)
        name = e.callee
        if name == "len" and len(e.args) == 1 and friendly.span_end(e) is not None:
            arg = unparse(e.args[0])
            return f"The length is a field: `{arg}.len`.", [Fix(f"Write `{arg}.len`", "safe", [
                Edit(e.line, e.col, e.line, e.col + e.length, f"{arg}.len", fname)])]
        local_funcs = [k for k in self.free_funcs if "::" not in k] + list(friendly.NAME_SYNONYMS.values())
        modules = friendly.std_functions().get(name, [])
        if len(modules) == 1:
            module = modules[0]
            stem = module.split(".")[-1]
            binds = self.mod_binds.get(self.scope_slug, {})
            local = next((loc for loc, slug in binds.items() if slug == stem), None)
            if local is not None:
                return f"`{name}` is in `{module}`: write `{local}.{name}(...)`.", [
                    friendly.rename_fix(e.line, e.col, name, f"{local}.{name}", fname, "safe")]
            return f"`{name}` is in `{module}`: add `import {module}` and write `{stem}.{name}(...)`.", [
                Fix(f"Import `{module}` and call `{stem}.{name}`", "safe", [
                    Edit(1, 1, 1, 1, f"import {module}\n", fname),
                    Edit(e.line, e.col, e.line, e.col + len(name), f"{stem}.{name}", fname)])]
        near = friendly.nearest(name, local_funcs, friendly.NAME_SYNONYMS)
        if near:
            sure = friendly.NAME_SYNONYMS.get(name) == near
            return f"Did you mean: `{near}`?", [friendly.rename_fix(e.line, e.col, name, near, fname,
                                                                    "safe" if sure else "likely")]
        return "Define the function with `fn ...` first.", []

    def _func_ref(self, e: Name, info: FuncInfo | None = None) -> str:
        """A function name used as a value: function pointer type `fn(A, B) -> R`."""
        if info is None:
            info = self.funcs[getattr(e, "func_key", e.name)]
        if info.is_extern or info.owner is not None:
            self._err(e, f"`{e.name}` cannot be used as a function value.",
                      "Wrap it: `fn(x: i32) -> i32 => name(x)`." if info.is_extern else None)
            return ERR
        for p in info.params:
            if p.mode not in ("val", "") or is_slice_type(p.ty) or self._drop(p.ty):
                self._err(e, f"`{e.name}` cannot be used as a function value: parameter `{p.name}` is `{p.mode or 'val'} {p.ty}`.",
                          "Only functions whose parameters are plain by-value types can be used as function values.")
                return ERR
        e.func_ref = True  # type: ignore[attr-defined]
        return make_fn([p.ty for p in info.params], info.ret)

    def _apply(self, e: Apply) -> str:
        """`f(x)(y)`: call the value of an expression."""
        t = self._expr(e.callee)
        if t == ERR:
            self._eval_args_quietly(e.args)
            return ERR
        if t in self.closures:
            return self._closure_call(e, e.callee, t)
        if is_fn_type(t) or is_boxed_fn(t):
            return self._indirect_call(e, e.callee, t, unparse(e.callee), e.args)
        self._err(e, f"`{unparse(e.callee)}` is a `{t}`, not a function; it cannot be called.")
        self._eval_args_quietly(e.args)
        return ERR

    def _indirect_call(self, e: Expr, callee_expr: Expr, fty: str, display: str, args: list[Expr]) -> str:
        if fty == ERR:  # already reported
            self._eval_args_quietly(args)
            return ERR
        params, ret = fn_parts(fty)
        e.callee_expr = callee_expr  # type: ignore[attr-defined]
        e.is_indirect = True  # type: ignore[attr-defined]
        infos = [ParamInfo(f"arg{i}", t, "val", None) for i, t in enumerate(params)]
        self._check_args(e, display, infos, args, None)  # type: ignore[arg-type]
        return ret

    def _field(self, e: FieldAccess, expected: str | None = None) -> str:
        if isinstance(e.obj, Name) and self._lookup(e.obj.name) is None:
            qual = self._qualified_item(e.obj.name, e.field_name, e)
            if qual is False:
                return ERR
            if isinstance(qual, str):
                if qual in self.consts:
                    e.const_key = qual  # type: ignore[attr-defined]
                    return self.consts[qual].ty
                if qual in self.enums or qual in self.generic_enums:
                    self._err(e, f"`{e.field_name}` is a type.",
                              f"Name a variant: `{e.obj.name}.{e.field_name}.Variant`.")
                    return ERR
                self._err(e, f"`{e.field_name}` is not a value in module `{e.obj.name}`.")
                return ERR
        target = self._enum_target(e.obj)
        if target is not None:  # `Shape.Empty`
            return self._variant_ctor(e, target, e.field_name, None, expected)
        ot = self._expr(e.obj)
        if ot == ERR:
            return ERR
        if e.field_name == "len":
            if is_array_type(ot) or is_slice_type(ot) or ot == "str":
                return "usize"
            if ot == "string":
                friendly.as_len_method(e)  # `s.len` and `s.len()` are the same length
                return self._method_call(e)  # type: ignore[arg-type]
        hk = heap_kind(ot)
        if hk == "List" and e.field_name == "len":
            return "usize"
        if hk in ("Box", "Shared", "Arc") and e.field_name == "value":
            return heap_inner(ot)
        if hk is not None:
            fields = "`value`" if hk in ("Box", "Shared", "Arc") else "`len`"
            self._err(e, f"Type `{ot}` has no field named `{e.field_name}`.", f"`{ot}` fields: {fields}.",
                      fixes=self._member_fix(e, e.field_name, ["value"] if hk in ("Box", "Shared", "Arc") else ["len"]))
            return ERR
        info = self.structs.get(ot)
        if info is None:
            self._err(e, f"Type `{ot}` has no fields (cannot use `.{e.field_name}`).")
            return ERR
        if e.field_name not in info.fields:
            fixes = self._member_fix(e, e.field_name, list(info.fields))
            hint = f"Did you mean: `{fixes[0].edits[0].replacement}`?" if fixes else \
                f"`{ot}` fields: {', '.join(info.fields)}."
            self._err(e, f"Struct `{ot}` has no field named `{e.field_name}`.", hint, fixes=fixes)
            return ERR
        if not self._field_ok(info, e.field_name, e):
            return ERR
        if getattr(info.decl, "is_union", False) and not self.unsafe_depth:
            self._err(e, f"`{unparse(e)}` reads the union `{ot}` as `{e.field_name}`: that needs `unsafe:`.",
                      "The bytes may have been written as another field; reading them as this one is your "
                      "responsibility.", rule="unsafe-required")
        return info.fields[e.field_name]

    def _member_fix(self, e: Expr, member: str, candidates: list[str]) -> list[Fix]:
        """Rename `.member` to the field or method it is closest to (`append` -> `push`)."""
        at = getattr(e, "member_at", None)
        near = friendly.nearest(member, candidates, friendly.METHOD_SYNONYMS)
        if at is None or near is None:
            return []
        sure = friendly.METHOD_SYNONYMS.get(member) == near
        return [friendly.rename_fix(at[0], at[1], member, near, getattr(e, "filename", None), "safe" if sure else "likely")]

    def _unary(self, e: Unary, expected: str | None) -> str:
        if e.op == "not":
            t = self._expr(e.operand, "bool")
            if t not in (ERR, "bool"):
                self._err(e.operand, f"`not` requires a `bool`, found `{t}`.")
                return ERR
            return "bool" if t != ERR else ERR
        if e.op == "~":
            exp = expected if (expected and expected in INTS) else None
            t = self._expr(e.operand, exp)
            if t not in (ERR,) and t not in INTS:
                self._err(e.operand, f"`~` can only be used with integers, found `{t}`.")
                return ERR
            return t
        if e.op == "-":
            if expected in UNSIGNED_INTS:
                self._err(e, f"Unary `-` cannot be used with unsigned type (`{expected}`).")
                return ERR
            if isinstance(e.operand, IntLit):
                if expected and is_bounded_int(expected):
                    base, lo, hi = bounded_int_info(expected)
                    val = -e.operand.value
                    if lo <= val < hi:
                        e.operand.ty = base
                        return expected
                    self._err(e, f"{val} is out of bounds for `{expected}` (range [{lo}, {hi})).")
                    return expected
                exp = expected if (expected and expected in (SIGNED_INTS | FLOATS)) else "i32"
                e.operand.ty = exp
                min_val, max_val = INT_RANGES[exp]
                val = -e.operand.value
                if not (min_val <= val <= max_val):
                    self._err(e, f"{val} is too small for `{exp}`.",
                              "Use `i64` for smaller/larger numbers." if exp == "i32" else None)
                return exp
            exp = expected if (expected and expected in (SIGNED_INTS | FLOATS)) else None
            t = self._expr(e.operand, exp)
            if t in self.structs or t in self.enums:  # `-v` -> `v.neg()`
                call = self._overload_call(e, t, "neg", e.operand, [], "-")
                if call is None:
                    return ERR
                e.overload = call  # type: ignore[attr-defined]
                return call.ty
            if t not in (ERR,) and t in UNSIGNED_INTS:
                self._err(e, f"Unary `-` cannot be used with unsigned type (`{t}`).")
                return ERR
            if t not in (ERR,) and t not in (SIGNED_INTS | FLOATS):
                self._err(e.operand, f"Unary `-` requires a number, found `{t}`.")
                return ERR
            return t
        raise AssertionError(f"unexpected unary operator: {e.op}")

    def _is_null(self, e: Expr) -> bool:
        return isinstance(e, Name) and e.name == "null" and self._lookup("null") is None

    OVERLOAD_METHODS = {
        "+": "add", "-": "sub", "*": "mul", "/": "div", "%": "rem", "&": "bitand", "|": "bitor", "^": "bitxor",
        "==": "eq", "!=": "eq", "<": "lt", "<=": "le", ">": "gt", ">=": "ge",
    }

    def _overload_call(self, e: Expr, lt: str, method: str, obj: Expr, args: list[Expr], shown: str) -> str | None:
        """Operator on a struct/enum value: resolved to method `method` (`a + b` -> `a.add(b)`). Returns the call."""
        info = self.funcs.get(f"{lt}.{method}") or self._method_template_info(lt, method, e)
        if info is None:
            self._err(e, f"Type `{lt}` does not support operator `{shown}`.",
                      f"Define `fn {lt}.{method}(self: {lt}, ...)` to overload it.")
            return None
        call = MethodCall(obj, method, args)
        call.line, call.col, call.length, call.filename = e.line, e.col, e.length, getattr(e, "filename", None)
        call.ty = self._method_call(call, None)
        return call

    def _overload_binary(self, e: Binary, lt: str) -> str:
        method = self.OVERLOAD_METHODS[e.op]
        call = self._overload_call(e, lt, method, e.left, [e.right], e.op)
        if call is None:
            return ERR
        ty = call.ty
        is_cmp = e.op in COMPARE_OPS
        if is_cmp and ty not in (ERR, "bool"):
            self._err(e, f"Operator method `{lt}.{method}` must return `bool`, found `{ty}`.")
            return ERR
        if e.op == "!=":
            node = Unary("not", call)
            node.line, node.col, node.length = e.line, e.col, e.length
            node.ty = "bool"
            e.overload = node  # type: ignore[attr-defined]
        else:
            e.overload = call  # type: ignore[attr-defined]
        return ty

    def _binary(self, e: Binary, expected: str | None) -> str:
        op = e.op
        if op in ("and", "or"):
            lt = self._expr(e.left, "bool")
            rt = self._expr(e.right, "bool")
            for side, t in ((e.left, lt), (e.right, rt)):
                if t not in (ERR, "bool"):
                    self._err(side, f"`{op}` requires `bool` on both sides, found `{t}`.")
            return "bool"
        if op in ("<<", ">>"):
            exp = expected if (expected and expected in INTS) else None
            lt = self._expr(e.left, exp)
            rt = self._expr(e.right, "i32")
            if ERR in (lt, rt):
                return ERR
            if lt not in INTS:
                self._err(e.left, f"`{op}` left operand must be an integer, found `{lt}`.")
                return ERR
            if rt not in INTS:
                self._err(e.right, f"`{op}` right operand (shift amount) must be an integer, found `{rt}`.")
                return ERR
            return lt
        if op in ("wrapping_add", "wrapping_sub", "wrapping_mul",
                  "saturating_add", "saturating_sub", "saturating_mul",
                  "checked_add", "checked_sub", "checked_mul"):
            if op in ("checked_add", "checked_sub", "checked_mul", "saturating_mul"):
                call = Call(op, [e.left, e.right])
                call.line, call.col, call.length = e.line, e.col, getattr(e, "length", 1)
                call.filename = getattr(e, "filename", None)
                t = self._call(call, expected)
                e.__class__ = Call
                e.__dict__.update(call.__dict__)
                return t
            base_exp = bounded_int_info(expected)[0] if (expected and is_bounded_int(expected)) else expected
            exp = base_exp if (base_exp and base_exp in INTS) else None
            lt = self._expr(e.left, exp)
            base_lt = bounded_int_info(lt)[0] if is_bounded_int(lt) else lt
            rt = self._expr(e.right, base_lt if base_lt in INTS else None)
            base_rt = bounded_int_info(rt)[0] if is_bounded_int(rt) else rt
            if ERR in (lt, rt):
                return ERR
            if base_lt not in INTS:
                self._err(e.left, f"`{op}` operand must be an integer, found `{lt}`.")
                return ERR
            if base_rt != base_lt:
                self._err(e.right, f"Both operands of `{op}` must have the same type: `{lt}` and `{rt}`.")
                return ERR
            return lt
        arith = op not in COMPARE_OPS
        if op in ("==", "!=") and (self._is_null(e.left) or self._is_null(e.right)):  # `p == null`
            other, nul = (e.right, e.left) if self._is_null(e.left) else (e.left, e.right)
            ot = self._expr(other)
            if ot != ERR and not is_ptr_type(ot):
                self._err(e, f"`null` can only be compared with a pointer, found `{ot}`.")
                self._expr(nul, None)
            elif ot != ERR:
                self._expr(nul, ptr_const(ot))
            return "bool"
        base_exp = bounded_int_info(expected)[0] if (expected and is_bounded_int(expected)) else expected
        exp = base_exp if (arith and base_exp in NUMERIC) else None
        if _is_const_expr(e.left) and not _is_const_expr(e.right):
            rt = self._expr(e.right)
            base_rt = bounded_int_info(rt)[0] if is_bounded_int(rt) else rt
            lt = self._expr(e.left, base_rt if base_rt in NUMERIC else None)
        else:
            lt = self._expr(e.left, exp)
            base_lt = bounded_int_info(lt)[0] if is_bounded_int(lt) else lt
            rt = self._expr(e.right, base_lt if base_lt in NUMERIC else None)
        result = ERR if arith else "bool"
        if ERR in (lt, rt):
            return result
        if is_simd(lt) or is_simd(rt):
            return self._simd_binary(e, op, lt, rt)
        if op == "+" and (lt in ("str", "string") or rt in ("str", "string")):
            valid = True
            for side, t in ((e.left, lt), (e.right, rt)):
                if t not in PRIMS and t != "string" and f"{t}.to_string" not in self.funcs:
                    self._err(side, f"Type `{t}` cannot be concatenated with `+`.",
                              f"Convert `{t}` to string or define `fn {t}.to_string(self: read {t}) -> string:`.")
                    valid = False
            return "string" if valid else ERR
        if lt in self.structs or lt in self.enums:
            m = self.OVERLOAD_METHODS.get(op)
            if m is not None and (op not in COMPARE_OPS or f"{lt}.{m}" in self.funcs
                                  or self._method_template_info(lt, m, e) is not None):
                return self._overload_binary(e, lt)
        base_lt = bounded_int_info(lt)[0] if is_bounded_int(lt) else lt
        base_rt = bounded_int_info(rt)[0] if is_bounded_int(rt) else rt
        if lt != rt and base_lt != base_rt and base_lt in NUMERIC and base_rt in NUMERIC:
            # The narrower side converts when that keeps every value (`i64 + i32`, `f64 * i32`).
            if base_lt in friendly.WIDENS.get(base_rt, ()) or self._counter_fits(e.right, base_lt):
                friendly.wrap_in_cast(e.right, base_lt)
                rt, base_rt = base_lt, base_lt
                lt = base_lt
            elif base_rt in friendly.WIDENS.get(base_lt, ()) or self._counter_fits(e.left, base_rt):
                friendly.wrap_in_cast(e.left, base_rt)
                lt, base_lt = base_rt, base_rt
                rt = base_rt
        if lt != rt and base_lt != base_rt and not (is_ptr_type(lt) and is_ptr_type(rt) and ptr_const(lt) == ptr_const(rt)):
            fixes: list[Fix] = []
            hint = "Convert one side: no conversion between these types keeps every value."
            if base_lt in NUMERIC and base_rt in NUMERIC:
                fixes = friendly.wrap_fix(e.right, f"{base_lt}(", ")", f"Convert the right side with `{base_lt}(...)`") + \
                    friendly.wrap_fix(e.left, f"{base_rt}(", ")", f"Convert the left side with `{base_rt}(...)`")
                hint = f"Write `{base_lt}(...)` around the right side or `{base_rt}(...)` around the left side."
            self._err(e, f"Both sides of `{op}` must have the same type: found `{lt}` and `{rt}`.", hint, fixes=fixes)
            return result
        if arith:
            if op in ("%", "&", "|", "^") and base_lt not in INTS:
                self._err(e, f"`{op}` can only be used with integers, found `{lt}`.")
                return ERR
            if base_lt not in NUMERIC:
                self._err(e, f"`{op}` can only be used with numbers, found `{lt}`.")
                return ERR
            if op == "&":
                if isinstance(e.right, IntLit) and e.right.value >= 0:
                    return make_bounded_int(base_lt, 0, e.right.value + 1)
                if isinstance(e.left, IntLit) and e.left.value >= 0:
                    return make_bounded_int(base_lt, 0, e.left.value + 1)
            if op == "%":
                if isinstance(e.right, IntLit) and e.right.value > 0 and (base_lt in UNSIGNED_INTS or (is_bounded_int(lt) and bounded_int_info(lt)[1] >= 0)):
                    return make_bounded_int(base_lt, 0, e.right.value)
            return lt
        if op in ("==", "!="):
            if base_lt not in NUMERIC and base_lt not in ("bool", "str") and not is_ptr_type(base_lt):
                bad = self._eq_problem(lt, e)
                if bad is None:
                    e.structural_eq = lt  # type: ignore[attr-defined]  # field by field (codegen eq_fn)
                else:
                    self._err(e, f"Type `{lt}` cannot be compared with `{op}`." if bad == lt else
                              f"Type `{lt}` cannot be compared with `{op}`: it contains `{bad}`.",
                              f"Values compare field by field; `{bad}` has no `==`. Define "
                              f"`fn eq(self: Self, other: Self) -> bool` in `impl {lt}:`." if lt in self.structs
                              or lt in self.enums else None)
        elif base_lt in ("str", "string"):
            e.text_order = base_lt  # type: ignore[attr-defined]  # byte by byte, then the shorter first
        elif base_lt not in NUMERIC:
            self._err(e, f"`{op}` only compares numbers and text, found `{lt}`.")
        return "bool"

    def _call(self, e: Call, expected: str | None = None) -> str:
        if getattr(e, "qualifier", None):
            return self._qualified_call(e)
        if e.callee in ("print", "eprint"):
            return self._print(e)
        if e.callee == "panic":
            return self._panic(e)
        if e.callee == "compile_error":
            return self._compile_error(e)
        if e.callee == "input":
            return self._input(e)
        if e.callee in ("target_os", "target_arch") and self._lookup(e.callee) is None:
            if e.args:  # `target_os()`: the platform being compiled for, a constant `str`
                self._err(e, f"`{e.callee}()` takes no arguments.")
                self._eval_args_quietly(e.args)
            e.builtin = e.callee  # type: ignore[attr-defined]
            return "str"
        if e.callee in PTR_BUILTINS:
            return self._ptr_builtin(e)
        if e.callee in SIMD_TYPES and self._lookup(e.callee) is None:
            return self._simd_ctor(e)
        if e.callee in INT_BUILTINS and self._lookup(e.callee) is None:
            return self._int_builtin(e)
        if e.callee in SHORT_CTORS and SHORT_CTORS[e.callee] in self.generic_enums:  # Some(x), Ok(x), Err(e)
            return self._variant_ctor(e, (SHORT_CTORS[e.callee], None), e.callee, e.args, expected)
        if e.callee in HEAP_BUILTINS:
            return self._heap_ctor(e, expected)
        if e.callee == "hash" and self._lookup("hash") is None and self._visible_func("hash") is None:
            return self._hash_builtin(e)
        if e.callee in ("to_json", "from_json") and self._lookup(e.callee) is None                 and self._visible_func(e.callee) is None:
            return self._json_builtin(e)
        if e.type_args and len(e.type_args) == 1 and self._lookup(e.callee) is not None                 and not e.type_args[0].args and not e.type_args[0].is_fn:
            # `handlers[i](x)`: a variable indexed by `i`, then called (read as a generic call by the parser)
            obj = _at(Name(e.callee), e)
            index = _at(Name(e.type_args[0].name), e.type_args[0])
            _replace(e, _at(Apply(_at(IndexAccess(obj, index), e), e.args), e))
            return self._apply(e)  # type: ignore[arg-type]
        gkey = self._resolve_simple(e.callee)
        if gkey is not None and gkey in self.generic_funcs:
            e.func_key = gkey  # type: ignore[attr-defined]
            return self._generic_call(e)
        if e.callee in self.tparams:  # T(x) in body
            return self._tparam_cast(e)
        var = self._lookup(e.callee)
        if var is not None and var.ty in self.closures:  # `f(x)` on a closure
            target = Name(e.callee)
            target.line, target.col, target.length = e.line, e.col, len(e.callee)
            target.filename = getattr(e, "filename", None)
            self._expr(target)
            return self._closure_call(e, target, var.ty)
        if var is not None and (is_fn_type(var.ty) or is_boxed_fn(var.ty)):  # call through a function value
            if e.type_args:
                self._err(e, f"`{e.callee}` is a function value; it takes no type arguments.")
            callee = Name(e.callee)
            callee.line, callee.col, callee.length = e.line, e.col, len(e.callee)
            callee.filename = getattr(e, "filename", None)
            self._expr(callee)
            return self._indirect_call(e, callee, var.ty, e.callee, e.args)
        info = self._visible_func(e.callee)
        if info is not None:
            e.func_key = info.key  # type: ignore[attr-defined]
        if info is None and var is not None and var.ty != ERR:
            self._err(e, f"`{e.callee}` is a `{var.ty}`, not a function; it cannot be called.")
            self._eval_args_quietly(e.args)
            return ERR
        if info is None or info.owner is not None:
            owners = self._variant_owners(e.callee)
            if owners:
                self._err(e, f"`{e.callee}` is a variant name; qualifier is required.",
                          f"Write `{owners[0]}.{e.callee}(...)` (variants are qualified by enum name).")
                for a in e.args:
                    self._expr_any(a)
                return ERR
            if e.callee == "string" and len(e.args) == 1:
                arg_ty = self._expr(e.args[0])
                if arg_ty in PRIMS or arg_ty == "string" or f"{arg_ty}.to_string" in self.funcs:
                    e.is_string_conv = True  # type: ignore[attr-defined]
                    return "string"
                self._err(e.args[0], f"Type `{arg_ty}` cannot be converted to `string`.",
                          f"Define `fn {arg_ty}.to_string(self: read {arg_ty}) -> string:`.")
                return ERR
            hint, fixes = self._unknown_call_help(e)
            if e.callee in self.structs:
                hint = f"To construct a struct, write `{e.callee}{{ field: value }}`."
            self._err(e, f"No function named `{e.callee}`.", hint, fixes=fixes)
            for a in e.args:
                self._expr_any(a)
            return ERR
        if e.type_args:
            self._err(e, f"`{e.callee}` is not a generic function, cannot take type arguments.",
                      f"Write `{e.callee}(...)`.")
        e.is_extern = info.is_extern
        if info.is_extern:
            e.extern_symbol = info.decl.c_symbol or info.decl.name  # type: ignore[attr-defined]
        variadic = info.is_extern and bool(getattr(info.decl, "variadic", False))
        if variadic:
            n = len(info.params)
            if len(e.args) < n:
                self._err(e, f"`{e.callee}` expects at least {n} arguments, found {len(e.args)}.")
                for a in e.args:
                    self._expr_any(a)
                return info.ret
            self._check_args(e, e.callee, info.params, e.args[:n], None)
            e.vararg_tys = []  # type: ignore[attr-defined]
            for a in e.args[n:]:
                t = self._expr(a)
                if t != ERR and t not in NUMERIC and t not in ("bool", "str") and not is_ptr_type(t):
                    self._err(a, f"Cannot pass `{t}` as a variadic argument.",
                              "Only numeric, `bool`, `string` and pointer types may be passed.")
                e.vararg_tys.append(t)  # type: ignore[attr-defined]
        else:
            if not info.is_extern:
                spec = self._specialize_for_closures(info, e.args, e)
                if spec is not info:
                    e.inst_key = spec.key
                    info = spec
            self._check_args(e, e.callee, info.params, e.args, None)
        if info.is_extern and not self.unsafe_depth and (
                variadic or is_ptr_type(info.ret) or any(is_ptr_type(p.ty) for p in info.params)):
            self._err(e, f"`{e.callee}` takes/returns pointer or is variadic: call can only be made in an `unsafe:` block.",
                      "Place the call inside `unsafe:`; verifying C semantics is your responsibility.")
        self._mark_view(e, info)
        return info.ret

    def _mark_view(self, e: Call | MethodCall, info: FuncInfo) -> None:
        # The borrow checker reads the callee's view-flow summary through this id.
        e.callee_id = None if info.is_extern else id(info.decl)  # type: ignore[attr-defined]
        e.is_view = info.ret_view
        if not info.ret_view:
            return
        e.view_ptr = True  # type: ignore[attr-defined]
        e.view_lend = info.ret_lend  # type: ignore[attr-defined]
        tie_expr = self._ret_tie_expr(e, info)
        e.tie_expr = tie_expr  # type: ignore[attr-defined]
        e.tie_root = self._tie_root(tie_expr) if tie_expr is not None else None  # type: ignore[attr-defined]

    def _ret_tie_expr(self, e: Call | MethodCall, info: FuncInfo) -> Expr | None:
        origin = info.ret_origin or (info.params[0].name if info.params else None)
        if origin is None:
            return e.obj if isinstance(e, MethodCall) else (e.args[0] if e.args else None)
        idx = next((i for i, p in enumerate(info.params) if p.name == origin), 0)
        if isinstance(e, MethodCall):
            if idx == 0:
                return e.obj
            return e.args[idx - 1] if idx - 1 < len(e.args) else e.obj
        return e.args[idx] if idx < len(e.args) else None

    def _int_builtin(self, e: Call) -> str:
        """`add_overflows(a, b)` (also sub/mul) -> bool; `max_value[T]()` / `min_value[T]()` -> T."""
        name = e.callee
        if name in ("max_value", "min_value"):
            if len(e.type_args) != 1 or e.args:
                self._err(e, f"`{name}` used incorrectly.", f"Correct form: `{name}[i32]()`.")
                self._eval_args_quietly(e.args)
                return ERR
            ty = self._resolve(e.type_args[0])
            if ty == ERR:
                return ERR
            if ty not in INTS:
                self._err(e.type_args[0], f"`{name}` requires an integer type, found `{ty}`.")
                return ERR
            lo, hi = INT_RANGES[ty]
            e.builtin = "int_const"  # type: ignore[attr-defined]
            e.const_value = hi if name == "max_value" else lo  # type: ignore[attr-defined]
            return ty
        if len(e.args) != 2 or e.type_args:
            self._err(e, f"`{name}` used incorrectly.", f"Correct form: `{name}(a, b)`.")
            self._eval_args_quietly(e.args)
            return ERR
        lt = self._expr(e.args[0])
        rt = self._expr(e.args[1], lt if lt in INTS else None)
        if ERR in (lt, rt):
            return "bool"
        if lt not in INTS or rt != lt:
            self._err(e, f"`{name}` requires two integers of the same type, found `{lt}` and `{rt}`.")
            return "bool"
        e.builtin = "ovf_" + name.split("_")[0]  # type: ignore[attr-defined]
        return "bool"

    def _ptr_builtin(self, e: Call) -> str:
        """FFI pointer builtins (all require `unsafe:`): addr, addr_mut, ptr_cast, ptr_to_int, int_to_ptr,
        ptr_offset, cstr_to_string, string_to_cstr and their descriptive aliases (pointer_cast, address_of, etc.)."""
        orig_name = e.callee
        name = PTR_BUILTIN_ALIASES.get(orig_name, orig_name)
        e.builtin = "ptr_" + name  # type: ignore[attr-defined]
        if name.startswith("atomic_") or name == "fence":
            return self._atomic_builtin(e, name)
        if name == "asm":
            return self._asm_builtin(e)
        if name in ("size_of", "align_of"):  # layout queries are safe
            if len(e.type_args) != 1 or e.args:
                self._err(e, f"`{name}` used incorrectly.", f"Correct form: `{name}[T]()`.")
                self._eval_args_quietly(e.args)
                return ERR
            t = self._resolve(e.type_args[0])
            e.mem_ty = t  # type: ignore[attr-defined]
            return "usize" if t != ERR else ERR
        if not self.unsafe_depth:
            self._err(e, f"`{orig_name}` can only be called in an `unsafe:` block.",
                      "Place the relevant lines inside `unsafe:`.")
        want_targs = 1 if name in ("ptr_cast", "int_to_ptr", "ptr_read", "ptr_write", "volatile_read",
                                   "volatile_write") else 0
        want_args = {"addr": 1, "addr_mut": 1, "ptr_cast": 1, "ptr_to_int": 1, "int_to_ptr": 1, "ptr_offset": 2,
                     "cstr_to_string": 1, "string_to_cstr": 1, "str_from_raw": 2, "ptr_read": 1, "ptr_write": 2,
                     "volatile_read": 1, "volatile_write": 2}[name]
        if len(e.type_args) != want_targs or len(e.args) != want_args:
            sig = {"addr": "addr(x)", "addr_mut": "addr_mut(x)", "ptr_cast": "ptr_cast[*T](p)",
                   "ptr_to_int": "ptr_to_int(p)", "int_to_ptr": "int_to_ptr[*T](n)", "ptr_offset": "ptr_offset(p, n)",
                   "cstr_to_string": "cstr_to_string(p)", "string_to_cstr": "string_to_cstr(s)",
                   "str_from_raw": "str_from_raw(p, len)", "ptr_read": "ptr_read[T](p)",
                   "ptr_write": "ptr_write[T](p, value)", "volatile_read": "volatile_read[T](p)",
                   "volatile_write": "volatile_write[T](p, value)"}[name]
            self._err(e, f"`{name}` used incorrectly.", f"Correct form: `{sig}`.")
            for a in e.args:
                self._expr_any(a)
            return ERR
        if name in ("addr", "addr_mut"):
            arg = e.args[0]
            t = self._expr(arg)
            if t == ERR:
                return ERR
            if not self._is_place_expr(arg):
                self._err(arg, f"`{name}` applies to a variable, field, or element; `{unparse(arg)}` is not a place.",
                          "Assign the value to a variable first.")
                return ERR
            if self._drop(t):  # the bytes of an owner, for `ptr_read`/`ptr_write`: an untyped byte pointer
                e.addr_kind = "val"  # type: ignore[attr-defined]
                return make_ptr("u8", name == "addr_mut")
            if name == "addr_mut" and not self._check_mutable(arg, "lend"):
                return ERR
            if is_array_type(t):
                elem, kind = array_info(t)[1], "array"
            elif is_slice_type(t):
                elem, kind = slice_elem_type(t), "slice"
            elif t == "str":
                if name == "addr_mut":
                    self._err(arg, "String is immutable; `addr_mut` cannot be used.", "Use `addr` or `string_to_cstr`.")
                    return ERR
                elem, kind = "u8", "str"
            else:
                elem, kind = t, "val"
            e.addr_kind = kind  # type: ignore[attr-defined]
            return make_ptr(elem, name == "addr_mut")
        if name in ("volatile_read", "volatile_write"):
            # A memory-mapped register or memory another device changes: every read and write happens,
            # in program order, and the compiler does not merge or remove them.
            target = self._resolve(e.type_args[0])
            e.mem_ty = target  # type: ignore[attr-defined]
            if target != ERR and target not in NUMERIC and target != "bool" and not is_ptr_type(target):
                self._err(e.type_args[0], f"`{name}` works on numbers, `bool`, and pointers, not `{target}`.")
                self._eval_args_quietly(e.args)
                return ERR
            t = self._expr(e.args[0])
            if t != ERR and not is_ptr_type(t):
                self._err(e.args[0], f"`{name}` requires a pointer, found `{t}`.")
                return ERR
            if name == "volatile_write":
                if t != ERR and not ptr_is_mut(t):
                    self._err(e.args[0], f"`volatile_write` requires a mutable pointer (`*mut T`), found `{t}`.")
                vt = self._expr(e.args[1], target)
                self._expect_type(target, vt, e.args[1])
                return VOID
            return target
        if name in ("ptr_read", "ptr_write"):
            # Raw memory as a value of any type, heap owners included: `ptr_read` moves the value out
            # (the memory is uninitialized afterwards), `ptr_write` moves one in without dropping the old bytes.
            target = self._resolve(e.type_args[0])
            e.mem_ty = target  # type: ignore[attr-defined]
            if name == "ptr_read":
                t = self._expr(e.args[0])
                if t != ERR and not is_ptr_type(t):
                    self._err(e.args[0], f"`ptr_read` requires a pointer, found `{t}`.")
                    return ERR
                return target if t != ERR else ERR
            if target == ERR:
                self._eval_args_quietly(e.args)
                return ERR
            self._check_args(e, "ptr_write", [ParamInfo("p", "*mut u8", "val", None),
                                              ParamInfo("value", target, "consume" if self._moves(target) else "val", None)],
                             e.args)
            t = e.args[0].ty or ERR
            if t != ERR and not (is_ptr_type(t) and ptr_is_mut(t)):
                self._err(e.args[0], f"`ptr_write` requires a mutable pointer (`*mut T`), found `{t}`.")
            return VOID
        if name == "ptr_cast":
            target = self._resolve(e.type_args[0])
            t = self._expr(e.args[0])
            if ERR in (target, t):
                return ERR
            if not is_ptr_type(target):
                self._err(e.type_args[0], f"`ptr_cast` target must be a pointer type, found `{target}`.", "E.g. `ptr_cast[*u8](p)`.")
                return ERR
            if not is_ptr_type(t):
                self._err(e.args[0], f"`ptr_cast` requires a pointer, found `{t}`.", "Use `int_to_ptr` for integer to pointer.")
                return ERR
            return target
        if name == "ptr_to_int":
            t = self._expr(e.args[0])
            if t != ERR and not is_ptr_type(t):
                self._err(e.args[0], f"`ptr_to_int` requires a pointer, found `{t}`.")
                return ERR
            return "usize" if t != ERR else ERR
        if name == "int_to_ptr":
            target = self._resolve(e.type_args[0])
            t = self._expr(e.args[0], "usize")
            if ERR in (target, t):
                return ERR
            if not is_ptr_type(target):
                self._err(e.type_args[0], f"`int_to_ptr` target must be a pointer type, found `{target}`.")
                return ERR
            self._expect_type("usize", t, e.args[0])
            return target
        if name == "ptr_offset":
            t = self._expr(e.args[0])
            n = self._expr(e.args[1], "isize")
            if ERR in (t, n):
                return ERR
            if not is_ptr_type(t) or ptr_elem(t) == "void":
                self._err(e.args[0], f"`ptr_offset` requires a concrete pointer (`*void` not allowed), found `{t}`.")
                return ERR
            if n not in INTS:
                self._err(e.args[1], f"`ptr_offset` offset must be an integer, found `{n}`.")
                return ERR
            return t
        if name == "str_from_raw":  # `str` view over `len` bytes at `p` (no NUL terminator is implied)
            t = self._expr(e.args[0])
            n = self._expr(e.args[1], "usize")
            if t != ERR and ptr_const(t) != "*u8":
                self._err(e.args[0], f"`str_from_raw` requires `*u8`, found `{t}`.")
                return ERR
            if n != ERR:
                self._expect_type("usize", n, e.args[1])
            return "str" if ERR not in (t, n) else ERR
        if name == "cstr_to_string":
            t = self._expr(e.args[0])
            if t != ERR and ptr_const(t) != "*u8" and ptr_const(t) != "*i8":
                self._err(e.args[0], f"`cstr_to_string` requires `*u8`, found `{t}`.")
                return ERR
            return "str" if t != ERR else ERR
        # string_to_cstr
        t = self._expr(e.args[0])
        if t != ERR and t != "str":
            self._err(e.args[0], f"`string_to_cstr` requires a `string`, found `{t}`.")
            return ERR
        return "*u8" if t != ERR else ERR

    def _asm_builtin(self, e: Call) -> str:
        """`asm[T]("template", "constraints", args...)`: inline machine code, in LLVM's inline-asm syntax.

        The constraints name an output first when there is a result (`"=r,r"`), then one input per
        argument; `~{memory}` says the code reads or writes memory. Arguments are numbers, `bool`, or
        pointers. The code always runs; the compiler does not remove or move it past other side effects.
        """
        if not self.unsafe_depth:
            self._err(e, "`asm` can only be used in an `unsafe:` block.",
                      "Inline machine code can do anything; put it inside `unsafe:`.", rule="unsafe-required")
        if len(e.type_args) > 1 or len(e.args) < 2 or not all(isinstance(a, StrLit) for a in e.args[:2]):
            self._err(e, "`asm` used incorrectly.",
                      'Correct form: `asm("nop", "")` or `asm[u64]("mov $1, $0", "=r,r", x)`.')
            self._eval_args_quietly(e.args)
            return ERR
        ret = self._resolve(e.type_args[0]) if e.type_args else VOID
        if ret not in (VOID, ERR, "bool") and ret not in NUMERIC and not is_ptr_type(ret):
            self._err(e.type_args[0], f"`asm` can return a number, `bool`, or a pointer, not `{ret}`.")
            return ERR
        tys = []
        for a in e.args[2:]:
            t = self._expr(a)
            if t != ERR and t not in NUMERIC and t != "bool" and not is_ptr_type(t):
                self._err(a, f"`asm` takes numbers, `bool`, and pointers as inputs, not `{t}`.")
            tys.append(t)
        e.asm_arg_tys = tys  # type: ignore[attr-defined]
        return ret

    def _atomic_builtin(self, e: Call, name: str) -> str:
        """`atomic_add[i64](p, 1, "acq_rel")`: one indivisible operation on the integer at `p`.

        The last argument is the memory ordering, a string literal: "relaxed", "acquire", "release",
        "acq_rel", or "seq_cst". `atomic_cas(p, expected, new, order)` returns the value it found;
        it stored `new` only when that equals `expected`.
        """
        from .typeinfo import ATOMIC_ORDERS
        if not self.unsafe_depth:
            self._err(e, f"`{name}` can only be called in an `unsafe:` block.",
                      "Use `std.thread.Atomic[T]` for a safe atomic, or put the call inside `unsafe:`.",
                      rule="unsafe-required")
        values = {"fence": 0, "atomic_load": 0, "atomic_store": 1, "atomic_cas": 2}.get(name, 1)
        want_args = (0 if name == "fence" else 1) + values + 1
        sig = ("fence(order)" if name == "fence" else
               f"{name}[T](p" + "".join(f", {n}" for n in (["expected", "new"] if name == "atomic_cas" else
                                                             ["value"] if values else [])) + ", order)")
        if len(e.args) != want_args or len(e.type_args) != (0 if name == "fence" else 1):
            self._err(e, f"`{name}` used incorrectly.", f"Correct form: `{sig}`.")
            self._eval_args_quietly(e.args)
            return ERR
        order = e.args[-1]
        if not isinstance(order, StrLit) or order.value not in ATOMIC_ORDERS:
            self._err(order, f"The memory ordering must be one of {', '.join(repr(o) for o in ATOMIC_ORDERS)}.",
                      'Write it as a string literal, e.g. `"seq_cst"` (the strongest and the simplest to reason about).')
            return ERR
        bad = {"atomic_load": ("release", "acq_rel"), "atomic_store": ("acquire", "acq_rel")}.get(name, ())
        if order.value in bad or (name == "fence" and order.value == "relaxed"):
            self._err(order, f"`{name}` cannot use the ordering \"{order.value}\".",
                      'A load can be "relaxed", "acquire", or "seq_cst"; a store "relaxed", "release", or "seq_cst".')
            return ERR
        e.atomic_order = order.value  # type: ignore[attr-defined]
        if name == "fence":
            return VOID
        target = self._resolve(e.type_args[0])
        if target != ERR and target not in INTS:
            self._err(e.type_args[0], f"`{name}` works on integer types, not `{target}`.",
                      "Store a `bool` as a `u8`, a pointer as a `usize`.")
            self._eval_args_quietly(e.args[:-1])
            return ERR
        e.mem_ty = target  # type: ignore[attr-defined]
        p = self._expr(e.args[0])
        if p != ERR and not (is_ptr_type(p) and (name == "atomic_load" or ptr_is_mut(p))):
            self._err(e.args[0], f"`{name}` needs a {'' if name == 'atomic_load' else 'mutable '}pointer, found `{p}`.")
        for v in e.args[1:-1]:
            vt = self._expr(v, target)
            self._expect_type(target, vt, v)
        return VOID if name == "atomic_store" else target

    def _heap_ctor(self, e: Call, expected: str | None) -> str:
        """`List[T]()` empty list, `Box[T](value)` box. If type argument omitted, inferred from expected type."""
        kind = e.callee
        if e.type_args:
            if len(e.type_args) != 1:
                self._err(e, f"`{kind}` expects 1 type argument, found {len(e.type_args)}.")
                self._eval_args_quietly(e.args)
                return ERR
            inner = self._resolve(e.type_args[0])
            if not self._check_type_arg(inner, e.type_args[0]):
                self._eval_args_quietly(e.args)
                return ERR
        elif expected is not None and heap_kind(expected) == kind:
            inner = heap_inner(expected)
        else:
            self._err(e, f"Cannot determine type argument for `{kind}`.",
                      f"Write as `{kind}[i32](...)` or specify variable type: `x: {kind}[i32] = {kind}(...)`.")
            self._eval_args_quietly(e.args)
            return ERR
        if kind == "List":
            if e.args:
                self._err(e, f"`List[{inner}]()` takes no arguments; use `push` to add elements.")
                self._eval_args_quietly(e.args)
            e.builtin = "vec_new"
        else:
            params = [ParamInfo("value", inner, "consume" if self._moves(inner) else "val", None)]
            self._check_args(e, kind, params, e.args)
            e.builtin = "shared_new" if kind in SHARED_KINDS else "box_new"
        return make_generic(kind, [inner])

    def _builtin_clone(self, e: MethodCall, ot: str) -> bool:
        """`x.clone()`: deep copy of any value type, unless the type defines its own `clone`."""
        base = (generic_parts(ot) or (ot, []))[0]
        if f"{ot}.clone" in self.funcs or f"{base}.clone" in self.method_templates:
            return False
        if e.args:
            self._err(e, "`clone()` takes no arguments.")
            self._eval_args_quietly(e.args)
            return True
        if is_dyn_type(ot):
            self._err(e, f"`{ot.replace('::', '.')}` cannot be cloned: the concrete type is not known.",
                      "Add a method to the feature that returns a copy as the concrete type wraps it.")
            return True
        if heap_kind(ot) in SHARED_KINDS:  # adds an owner of the same value; nothing inside is copied
            e.owner = ot
            e.builtin = "clone"  # type: ignore[attr-defined]
            return True
        owner = self._drop_inside(ot)
        if owner is not None:
            self._err(e, f"`{ot}` cannot be cloned: `{owner}` has a destructor (`drop`).",
                      f"A copy would run `drop` twice on the same resource. Define `fn clone(self) -> {owner}` "
                      f"on `{owner}` to say how a copy is made.",
                      rule="drop-misuse", details={"type": owner})
            return True
        handle = held_handle(ot, self.structs, self.enums)
        if handle is not None:
            self._err(e, f"`{ot}` cannot be cloned: it holds the OS handle `{handle}`.",
                      f"A clone would be a second, unrelated `{handle}`. Pass the original as `read`/`lend` instead.",
                      rule="handle-copy", details={"value": unparse(e.obj), "handle": handle})
            return True
        bad = self._lend_ref_inside(ot, set())
        if bad is not None or is_slice_type(ot):
            what = f"it holds a `lend` reference (`{bad}`)" if bad else "a slice is a view"
            self._err(e, f"`{ot}` cannot be cloned: {what}.",
                      "An exclusive reference cannot be duplicated. Clone the owner instead.")
            return True
        e.owner = ot
        e.builtin = "clone"  # type: ignore[attr-defined]
        return True

    def _has_user_drop(self, ty: str) -> bool:
        info = self.structs.get(ty) or self.enums.get(ty)
        return info is not None and info.user_drop

    def _drop_inside(self, ty: str, seen: set[str] | None = None) -> str | None:
        """A type with a destructor and no `clone` of its own, held by value inside `ty`, or None."""
        seen = set() if seen is None else seen
        if ty in seen:
            return None
        seen.add(ty)
        if self._has_user_drop(ty) and not getattr(self.structs.get(ty), "archetype", False):
            base = (generic_parts(ty) or (ty, []))[0]
            if f"{ty}.clone" in self.funcs or f"{base}.clone" in self.method_templates:
                return None
            return ty
        if heap_kind(ty) in ("List", "Box", "Shared", "Arc"):
            return self._drop_inside(heap_inner(ty), seen)
        if is_array_type(ty):
            return self._drop_inside(array_info(ty)[1], seen)
        if ty in self.structs:
            info = self.structs[ty]
            for fname, fty in info.fields.items():
                if fname not in info.field_modes:
                    found = self._drop_inside(fty, seen)
                    if found:
                        return found
        if ty in self.enums:
            for vinfo in self.enums[ty].variants.values():
                for pt in vinfo.payload:
                    found = self._drop_inside(pt, seen)
                    if found:
                        return found
        return None

    def _lend_ref_inside(self, ty: str, seen: set[str]) -> str | None:
        """Name of a `lend` reference field reachable inside `ty` (by value), or None."""
        if ty in seen:
            return None
        seen.add(ty)
        if heap_kind(ty) in ("List", "Box"):
            return self._lend_ref_inside(heap_inner(ty), seen)
        if ty in self.structs:
            info = self.structs[ty]
            for fname, fty in info.fields.items():
                if info.field_modes.get(fname) == "lend":
                    return f"{ty}.{fname}"
                if fname not in info.field_modes:
                    found = self._lend_ref_inside(fty, seen)
                    if found:
                        return found
        if ty in self.enums:
            for vinfo in self.enums[ty].variants.values():
                for pt in vinfo.payload:
                    found = self._lend_ref_inside(pt, seen)
                    if found:
                        return found
        return None

    def _vec_method(self, e: MethodCall, ot: str) -> str:
        inner = heap_inner(ot)
        m = e.method
        elem = ParamInfo("x", inner, "consume" if self._moves(inner) else "val", None)
        sigs = {
            "push": [elem],
            "pop": [],
            "clear": [],
            "reserve": [ParamInfo("n", "usize", "val", None)],
            "truncate": [ParamInfo("n", "usize", "val", None)],
            "resize": [ParamInfo("n", "usize", "val", None), ParamInfo("x", inner, "val", None)],
            "get": [ParamInfo("i", "usize", "val", None)],
            "swap": [ParamInfo("i", "usize", "val", None), ParamInfo("j", "usize", "val", None)],
            "swap_remove": [ParamInfo("i", "usize", "val", None)],
            "remove": [ParamInfo("i", "usize", "val", None)],
            "insert": [ParamInfo("i", "usize", "val", None), elem],
        }
        if inner == "u8":
            sigs["as_str"] = []  # expose byte buffer as `str` view (for String)
            sigs["push_str"] = [ParamInfo("text", "str", "val", None)]  # appends the bytes of a `str`
        if m in LIST_HELPERS and m not in sigs:
            return self._list_helper(e, ot, inner)
        if m not in sigs:
            self._err(e, f"Type `{ot}` has no method named `{m}`.",
                      f"`{ot}` methods: {', '.join(list(sigs) + sorted(LIST_HELPERS))} (use `.len` for length).",
                      fixes=self._member_fix(e, m, list(sigs) + sorted(LIST_HELPERS) + ["len"]))
            self._eval_args_quietly(e.args)
            return ERR
        if m == "resize" and self._moves(inner):
            self._err(e, f"`resize` fills with copies of one value; `{inner}` is moved, not copied.",
                      f"Grow the list with `push` in a loop, or keep copyable values (numbers, `str`, plain structs) in it.",
                      rule="list-helper-moved", details={"method": m, "element": inner})
            self._eval_args_quietly(e.args)
            return ERR
        e.owner = ot
        e.builtin = "vec_" + m
        if m in ("get", "as_str"):  # read-only view: element ownership is not transferred
            e.is_view = True
            if m == "get":
                e.view_ptr = True  # type: ignore[attr-defined]
                e.tie_root = self._tie_root(e.obj)  # type: ignore[attr-defined]
            recv_ro = ArgAccess("val", self._path(e.obj), ot, e.obj, e.obj, is_receiver=True)
            self._check_args(e, f"{unparse(e.obj)}.{m}", sigs[m], e.args, recv_ro)
            return inner if m == "get" else "str"
        e.self_lend = True
        e.self_mode = "lend"
        recv: ArgAccess | None = None
        if getattr(e.obj, "view_lend", False):
            pass  # `g.value().push(x)`: the call returned `lend List[T]`
        elif _place_path(e.obj) is None:
            self._err(e.obj, f"`{m}` is a mutating method; receiver must be a variable (or field).",
                      "Assign the value to a variable first.")
        elif self._check_mutable(e.obj, "method", m):
            recv = ArgAccess("lend", self._path(e.obj), ot, e.obj, e.obj, is_receiver=True)
        self._check_args(e, f"{unparse(e.obj)}.{m}", sigs[m], e.args, recv)
        if m == "pop":
            return self._instantiate_type("Optional", [inner], e)
        if m in ("swap_remove", "remove"):
            return inner
        return VOID

    def _list_helper(self, e: MethodCall, ot: str, inner: str) -> str:
        """`xs.map(f)`, `xs.sort()`, ...: a call of the Core function `_list_<name>(xs, ...)`."""
        m = e.method
        if m not in LIST_ANY_ELEM and self._moves(inner):
            self._err(e, f"`{m}` works on lists of copied elements; `{inner}` is moved, not copied.",
                      f"Walk the list with `for x in {unparse(e.obj)}:` instead, or keep copyable values "
                      f"(numbers, `str`, plain structs) in the list.",
                      rule="list-helper-moved", details={"method": m, "element": inner})
            self._eval_args_quietly(e.args)
            return ERR
        want_args = LIST_HELPER_ARGS.get(m, 0)
        if len(e.args) != want_args:
            shape = {0: "()", 1: "(f)" if m in LIST_CALLBACK_SLOT else "(x)", 2: "(init, f)"}[want_args]
            self._err(e, f"`{m}` expects {want_args} argument(s), found {len(e.args)}.",
                      "For the length, write `.len`." if m == "count" and not e.args else f"Write `{unparse(e.obj)}.{m}{shape}`.",
                      rule="wrong-arity")
            self._eval_args_quietly(e.args)
            return ERR
        slot = LIST_CALLBACK_SLOT.get(m)
        cb = e.args[slot[0]] if slot is not None and len(e.args) > slot[0] else None
        info = self.funcs.get(cb.name) if isinstance(cb, Name) and cb.name.startswith("__lambda_") else None
        if info is not None:
            got = [q.ty for q in info.params if q.name != "__env"]
            want = slot[1]
            bad = [i for i in want if i < len(got) and got[i] != inner]
            if bad:
                self._err(cb, f"The callback of `{m}` takes `{got[bad[0]]}`, but the list holds `{inner}`.",
                          f"Write the parameter as `{info.params[bad[0]].name}: {inner}`.",
                          rule="type-mismatch", details={"expected": inner, "found": got[bad[0]]})
                self._eval_args_quietly(e.args)
                return ERR
        new = _at(Call(f"_list_{m}", [e.obj] + list(e.args)), e)
        new.list_method = m  # type: ignore[attr-defined]
        _replace(e, new)
        return self._infer_inner(e, None)

    def _hash_builtin(self, e: Call) -> str:
        """`hash(x) -> u64`, chosen per type: integers, bool, str, string, or the type's own `hash` method."""
        if len(e.args) != 1:
            self._err(e, f"`hash` expects 1 argument, found {len(e.args)}.")
            self._eval_args_quietly(e.args)
            return ERR
        a = e.args[0]
        t = self._expr(a)
        if t == ERR:
            return ERR
        base = int_base(t)
        site = lambda n: _at(n, e)  # noqa: E731
        if base in INTS:
            new: Expr = site(Call("hash_mix64", [site(Cast("u64", a))]))
        elif base == "bool":
            new = site(Call("hash_flag", [a]))
        elif base in ("str", "string"):
            e.structural_hash = base  # type: ignore[attr-defined]  # codegen: eight bytes per step
            return "u64"
        elif f"{t}.hash" in self.funcs or self._method_template_info(t, "hash", e) is not None:
            new = site(MethodCall(a, "hash", []))
        elif self._eq_problem(t, e, hashing=True) is None:
            e.structural_hash = t  # type: ignore[attr-defined]  # field by field (codegen hash_fn)
            return "u64"
        else:
            bad = self._eq_problem(t, e, hashing=True)
            self._err(e, f"`{t}` cannot be hashed." if bad in (t, None) else f"`{t}` cannot be hashed: it contains `{bad}`.",
                      f"`{t}` defines its own `eq`, so a field-by-field hash could disagree with it. Define "
                      f"`fn hash(self: Self) -> u64` in `impl {t}:` that agrees with `eq`." if bad == t and f"{t}.eq" in self.funcs else
                      f"Values hash field by field, and a float has no exact hash. Define `fn hash(self: Self) -> u64` "
                      f"in `impl {t}:` (and `fn eq` for `==`)." if t in self.structs or t in self.enums else
                      "Hash integers, `bool`, text, and structs, enums, and lists of them.")
            return ERR
        _replace(e, new)
        return self._expr(e)

    def _compile_error(self, e: Call) -> str:
        """`compile_error("message")`: only in the body of an `attribute`; reports an error at the attribute's use."""
        types = [int_base(self._expr_any(a)) for a in e.args]
        if self.cur is None or not getattr(self.cur.decl, "attr_handler", False):
            self._err(e, "`compile_error` is only for the body of an `attribute`.",
                      "Write `attribute name(...) on fn:` and put the check under it.")
        elif len(types) != 1 or types[0] not in (ERR, "str", "string"):
            self._err(e, "`compile_error` takes one `str` message.", 'Write `compile_error("what is wrong")`.')
        return VOID

    def _panic(self, e: Call) -> str:
        """`panic("message")` / `panic(f"bad {x}")`: takes one `str` or `string`, returns void."""
        hint = 'Write as `panic("message")` or `panic(f"bad value: {x}")`.'
        if len(e.args) != 1:
            for a in e.args:
                self._expr_any(a)
            self._err(e, f"`panic` expects exactly 1 argument, found {len(e.args)}.", hint)
            return VOID
        a = e.args[0]
        t = int_base(self._expr(a, "str"))
        if t not in (ERR, "str", "string"):
            self._err(a, f"`panic` expects a `str` or `string` message, found `{t}`.",
                      'Put the value into an f-string: `panic(f"value: {x}")`.')
        return VOID

    def _print(self, e: Call) -> str:
        for a in e.args:
            t = int_base(self._expr(a))
            if t not in PRIMS and t not in (ERR, "string"):
                e.needs_show = True  # type: ignore[attr-defined]  # built as a `string` (see _used_core_funcs)
            bad = self._show_problem(t)
            if bad is not None:
                self._err(a, f"Type `{t}` cannot be printed." if bad == t else
                          f"Type `{t}` cannot be printed: it contains `{bad}`.",
                          f"Numbers, `bool`, text, structs, enums, lists, and arrays print; `{bad}` does not. "
                          f"Print a field instead, or define `fn to_string(self) -> string` in `impl`.")
        return VOID

    def _show_problem(self, ty: str, seen: frozenset[str] = frozenset()) -> str | None:
        """None when `print` and `f"{x}"` can show `ty`, otherwise the part that cannot be shown
        (a pointer, a function, an OS handle)."""
        ty = int_base(ty)
        if ty == ERR or ty in PRIMS or ty == "string" or ty in seen or f"{ty}.to_string" in self.funcs or is_simd(ty):
            return None
        seen = seen | {ty}
        if is_array_type(ty):
            return self._show_problem(array_info(ty)[1], seen)
        if is_slice_type(ty):
            return self._show_problem(slice_elem_type(ty), seen)
        if heap_kind(ty) in ("List", "Box", "Shared", "Arc") and not is_boxed_fn(ty):
            return self._show_problem(heap_inner(ty), seen)
        info = self.structs.get(ty)
        if info is not None and getattr(info.decl, "is_union", False):
            return ty  # which field holds the bytes is not known
        if info is not None and not info.handle:
            return next((bad for f in info.fields.values() if (bad := self._show_problem(f, seen))), None)
        einfo = self.enums.get(ty)
        if einfo is not None:
            return next((bad for v in einfo.variants.values() for p in v.payload
                         if (bad := self._show_problem(p, seen))), None)
        return ty

    def _own_method(self, ty: str, method: str, site: Node | None) -> bool:
        """Does `ty` define `method` itself (instantiating a generic type's method when needed)?"""
        if f"{ty}.{method}" in self.funcs:
            return True
        if site is None:  # a bound check: the method is instantiated later, at the use
            parts = generic_parts(ty)
            return parts is not None and f"{parts[0]}.{method}" in self.method_templates
        return self._method_template_info(ty, method, site) is not None

    def _eq_problem(self, ty: str, site: Node | None, hashing: bool = False,
                    seen: frozenset[str] = frozenset()) -> str | None:
        """None when `==` (or, with `hashing`, `hash`) works on `ty` field by field, otherwise the part that
        cannot be compared: a float when hashing, a pointer to code, an OS handle, a union, a `dyn` value."""
        ty = int_base(ty)
        if ty == ERR or ty in seen:
            return None
        if ty in NUMERIC:
            return ty if hashing and ty in FLOATS else None
        if ty in ("bool", "str", "string") or is_ptr_type(ty):
            return None
        if self._own_method(ty, "eq", site):  # its own `==`: a field-by-field hash could disagree with it
            return None if not hashing or self._own_method(ty, "hash", site) else ty
        seen = seen | {ty}
        if is_array_type(ty):
            return self._eq_problem(array_info(ty)[1], site, hashing, seen)
        if is_slice_type(ty):
            return self._eq_problem(slice_elem_type(ty), site, hashing, seen)
        if heap_kind(ty) in ("List", "Box", "Shared", "Arc") and not is_boxed_fn(ty):
            return self._eq_problem(heap_inner(ty), site, hashing, seen)
        info = self.structs.get(ty)
        if info is not None:
            if info.handle or getattr(info.decl, "is_union", False) or getattr(info, "archetype", False):
                return ty
            return next((bad for f in info.fields.values() if (bad := self._eq_problem(f, site, hashing, seen))), None)
        einfo = self.enums.get(ty)
        if einfo is not None:
            return next((bad for v in einfo.variants.values() for p in v.payload
                         if (bad := self._eq_problem(p, site, hashing, seen))), None)
        return ty

    def _json_problem(self, ty: str, decode: bool, seen: frozenset[str] = frozenset()) -> str | None:
        """None when `to_json` (or, with `decode`, `from_json`) handles `ty`; otherwise the part it cannot."""
        ty = int_base(ty)
        if ty in seen or ty in NUMERIC or ty in ("bool", "string"):
            return None
        if ty == "str" or is_slice_type(ty):
            return None if not decode else ty  # a view: decode into `string` or `List[T]` instead
        seen = seen | {ty}
        if not decode and f"{ty}.to_json" in self.funcs:
            return None
        if is_array_type(ty):
            return self._json_problem(array_info(ty)[1], decode, seen)
        hk = heap_kind(ty)
        if is_boxed_fn(ty) or is_dyn_type(ty):
            return ty
        if hk in ("List", "Box") or (hk in ("Shared", "Arc") and not decode):
            return self._json_problem(heap_inner(ty), decode, seen)
        if hk is not None:
            return ty
        info = self.structs.get(ty)
        if info is not None:
            if info.handle or info.field_modes or getattr(info.decl, "is_union", False) or getattr(info, "archetype", False):
                return ty
            return next((bad for f in info.fields.values() if (bad := self._json_problem(f, decode, seen))), None)
        einfo = self.enums.get(ty)
        if einfo is not None:
            return next((bad for v in einfo.variants.values() for p in v.payload
                         if (bad := self._json_problem(p, decode, seen))), None)
        return ty

    def _json_builtin(self, e: Call) -> str:
        """`to_json(x) -> string` and `from_json[T](text) -> Result[T, string]`, generated per type by codegen."""
        if e.callee == "to_json":
            if len(e.args) != 1:
                self._err(e, f"`to_json` expects 1 argument, found {len(e.args)}.", rule="wrong-arity")
                self._eval_args_quietly(e.args)
                return ERR
            t = self._expr(e.args[0])
            if t == ERR:
                return ERR
            bad = self._json_problem(t, decode=False)
            if bad is not None:
                self._err(e.args[0], f"`{t}` cannot be written as JSON" + (f": it contains `{bad}`." if bad != t else "."),
                          "Numbers, `bool`, text, lists, arrays, `Optional`, structs, and enums of them are JSON. "
                          f"A type can define `fn to_json(self) -> string`.", rule="not-printable")
                return ERR
            e.json_ty = t  # type: ignore[attr-defined]
            return "string"
        if len(e.type_args) != 1 or len(e.args) != 1:
            self._err(e, "Write `from_json[T](text)`: one type and one `str`.", rule="wrong-arity")
            self._eval_args_quietly(e.args)
            return ERR
        t = self._resolve(e.type_args[0])
        at = self._expr(e.args[0], "str")
        if ERR in (t, at):
            return ERR
        if int_base(at) not in ("str", "string"):
            self._err(e.args[0], f"`from_json` reads a `str`, found `{at}`.", rule="type-mismatch",
                      details={"expected": "str", "found": at})
            return ERR
        if int_base(at) == "string":
            e.args[0] = _at(MethodCall(e.args[0], "as_str", []), e.args[0])
            self._expr(e.args[0])
        bad = self._json_problem(t, decode=True)
        if bad is not None:
            self._err(e, f"`{t}` cannot be read from JSON" + (f": it contains `{bad}`." if bad != t else "."),
                      "Read into owned data: `string` instead of `str`, `List[T]` instead of a slice; pointers, "
                      "functions, OS handles, `Shared`, and `dyn` values have no JSON form.", rule="not-printable")
            return ERR
        e.json_ty = t  # type: ignore[attr-defined]
        e.json_decode = True  # type: ignore[attr-defined]
        return self._instantiate_type("Result", [t, "string"], e)

    def _input(self, e: Call) -> str:
        """`input()` or `input("prompt")`: takes optional string prompt, returns string."""
        hint = 'Write as `input()` or `input("prompt")`.'
        if len(e.args) > 1:
            self._err(e, f"`input` takes at most 1 argument, found {len(e.args)}.", hint)
            for a in e.args:
                self._expr_any(a)
            return "str"
        if len(e.args) == 1:
            a = e.args[0]
            t = self._expr(a, "str")
            if t != ERR and t != "str":
                self._expect_type("str", t, a)
        return "str"

    def _field_ok(self, info: StructInfo, field: str, node: Node) -> bool:
        decl = info.decl
        if getattr(decl, "from_prelude", False):
            return True
        slug = getattr(decl, "module_slug", "") or ""
        if slug == self.scope_slug:
            return True
        if info.field_pub.get(field, False):
            return True
        self._err(node, f"Field `{field}` is private in `{info.name}`.",
                  f"Put `{field}` under a `public` line in that struct.")
        return False

    def _qualified_call(self, e: Call) -> str:
        """`math.max[i32](1, 2)`."""
        key = self._qualified_item(e.qualifier or "", e.callee, e)
        if not isinstance(key, str):
            for a in e.args:
                self._expr_any(a)
            return ERR
        if key in self.generic_funcs:
            e.func_key = key  # type: ignore[attr-defined]
            return self._generic_call(e)
        info = self.funcs.get(key)
        if info is None or info.owner is not None:
            self._err(e, f"`{e.callee}` is not a function in module `{e.qualifier}`.")
            for a in e.args:
                self._expr_any(a)
            return ERR
        if e.type_args:
            self._err(e, f"`{e.qualifier}.{e.callee}` is not a generic function, cannot take type arguments.",
                      f"Write `{e.qualifier}.{e.callee}(...)`.")
        e.func_key = key  # type: ignore[attr-defined]
        e.is_extern = info.is_extern
        if info.is_extern:
            e.extern_symbol = info.decl.c_symbol or info.decl.name  # type: ignore[attr-defined]
        self._check_args(e, f"{e.qualifier}.{e.callee}", info.params, e.args, None)
        self._mark_view(e, info)
        return info.ret

    def _apply_generic(self, e: MethodCall, key: str) -> str:
        """`sort.sort(v)`: a generic function named through a module."""
        synth = Call(e.method, e.args)
        synth.func_key = key  # type: ignore[attr-defined]
        synth.line, synth.col, synth.length = e.line, e.col, e.length
        synth.filename = getattr(e, "filename", None)
        ty = self._generic_call(synth)
        e.func_key = key  # type: ignore[attr-defined]
        e.inst_key = getattr(synth, "inst_key", None)  # type: ignore[attr-defined]
        e.param_tys = getattr(synth, "param_tys", [])  # type: ignore[attr-defined]
        e.arg_modes = list(getattr(synth, "arg_modes", []))
        return ty

    def _generic_type_target(self, obj: Expr) -> tuple[str, list[TypeRef]] | None:
        """`Pair[i32, str]` or `mod.Pair[i32, str]` in receiver position, naming a generic struct."""
        base: str | None = None
        targs: list[TypeRef] | None = None
        if isinstance(obj, TypeApp):
            base, targs = self._resolve_simple(obj.name), obj.type_args
        elif isinstance(obj, IndexAccess) and obj.type_alt is not None:
            targs = obj.type_alt
            if isinstance(obj.obj, Name) and self._lookup(obj.obj.name) is None:
                base = self._resolve_simple(obj.obj.name)
            elif (isinstance(obj.obj, FieldAccess) and isinstance(obj.obj.obj, Name)
                  and self._lookup(obj.obj.obj.name) is None):
                qual = self._qualified_item(obj.obj.obj.name, obj.obj.field_name, obj, missing_ok=True)
                base = qual if isinstance(qual, str) else None
        if base is None or targs is None or base not in self.generic_structs:
            return None
        return base, targs

    def _generic_associated_call(self, e: MethodCall, base: str, targs: list[TypeRef]) -> str:
        ot = self._resolve_app(base, targs, e.obj)
        if ot == ERR:
            self._eval_args_quietly(e.args)
            return ERR
        info = self.funcs.get(f"{ot}.{e.method}") or self._method_template_info(ot, e.method, e)
        shown = ot.replace("::", ".")
        if info is None or not getattr(info.decl, "is_static", False):
            self._err(e, f"`{shown}` has no associated function `{e.method}`.",
                      "Call a method on a value instead: `x.{0}(...)`.".format(e.method))
            self._eval_args_quietly(e.args)
            return ERR
        if not self._is_visible(info.decl):
            self._err(e, f"`{e.method}` is private.", f"Put `{e.method}` under a `public` line in its module.")
            self._eval_args_quietly(e.args)
            return ERR
        e.static_key = info.key  # type: ignore[attr-defined]
        e.owner = ot
        self._check_args(e, f"{shown}.{e.method}", info.params, e.args, None)
        self._mark_view(e, info)
        return info.ret

    def _associated_call(self, e: MethodCall) -> str | None:
        """`thread.Thread.spawn(f)`. None when `e.obj` is not `module.Type`."""
        obj = e.obj
        if not isinstance(obj, FieldAccess) or not isinstance(obj.obj, Name) or self._lookup(obj.obj.name) is not None:
            return None
        slug = self.mod_binds.get(self.scope_slug, {}).get(obj.obj.name)
        if slug is None:
            return None
        key = f"{slug}::{obj.field_name}"
        decl = self._decl_for(key)
        if decl is None or not getattr(decl, "is_pub", False):
            self._eval_args_quietly(e.args)
            return ERR  # `_enum_target` already reported the missing or private name
        info = self.funcs.get(f"{key}.{e.method}")
        if info is None or not getattr(info.decl, "is_static", False):
            self._err(e, f"`{obj.obj.name}.{obj.field_name}` has no associated function `{e.method}`.")
            self._eval_args_quietly(e.args)
            return ERR
        if not self._is_visible(info.decl):
            self._err(e, f"`{e.method}` is private.",
                      f"Put `{e.method}` under a `public` line in its module.")
            self._eval_args_quietly(e.args)
            return ERR
        e.static_key = info.key  # type: ignore[attr-defined]
        e.owner = key
        self._check_args(e, f"{obj.obj.name}.{obj.field_name}.{e.method}", info.params, e.args, None)
        self._mark_view(e, info)
        return info.ret

    def _method_call(self, e: MethodCall, expected: str | None = None) -> str:
        if isinstance(e.obj, Name) and e.obj.name in SIMD_TYPES and self._lookup(e.obj.name) is None:
            return self._simd_static(e)
        if isinstance(e.obj, Name) and self._lookup(e.obj.name) is None:
            qual = self._qualified_item(e.obj.name, e.method, e, missing_ok=True)
            if qual is False:
                self._eval_args_quietly(e.args)
                return ERR
            if qual is None and e.obj.name in self.mod_binds.get(self.scope_slug, {}) and not self._is_type_name(e.obj.name):
                self._err(e, f"Module `{e.obj.name}` has no `{e.method}`.",
                          "Only names defined in that file can be used.")
                self._eval_args_quietly(e.args)
                return ERR
            if isinstance(qual, str) and qual in self.generic_funcs:
                return self._apply_generic(e, qual)
            if isinstance(qual, str) and qual in self.funcs and self.funcs[qual].owner is None:
                info = self.funcs[qual]
                e.func_key = qual  # type: ignore[attr-defined]
                e.is_extern = info.is_extern
                if info.is_extern:
                    e.extern_symbol = info.decl.c_symbol or info.decl.name  # type: ignore[attr-defined]
                self._check_args(e, f"{e.obj.name}.{e.method}", info.params, e.args, None)
                self._mark_view(e, info)
                return info.ret
        target = self._enum_target(e.obj)
        if target is not None and not self._enum_static(target[0], e.method):  # `Shape.Circle(1.0)`
            return self._variant_ctor(e, target, e.method, e.args, expected)
        generic = self._generic_type_target(e.obj)
        if generic is not None:  # `Queue[string].new()`
            return self._generic_associated_call(e, *generic)
        associated = self._associated_call(e)
        if associated is not None:
            return associated
        if isinstance(e.obj, Name) and self._lookup(e.obj.name) is None:
            owner_name = TYPE_ALIASES.get(e.obj.name, e.obj.name)
            found_owner = self._resolve_simple(owner_name)
            if found_owner is not None:
                owner_name = found_owner
            if owner_name in self.structs or owner_name in self.enums:
                sinfo = self.funcs.get(f"{owner_name}.{e.method}")
                if sinfo is not None and getattr(sinfo.decl, "is_static", False):  # `Vec2.new(1.0, 2.0)`
                    e.static_key = sinfo.key  # type: ignore[attr-defined]
                    e.owner = owner_name
                    self._check_args(e, sinfo.key, sinfo.params, e.args, None)
                    self._mark_view(e, sinfo)
                    return sinfo.ret
        ot = self._expr(e.obj)
        if ot == ERR:
            for a in e.args:
                self._expr_any(a)
            return ERR
        if is_dyn_type(ot):
            return self._dyn_method_call(e, ot)
        if is_simd(ot):
            return self._simd_method(e, ot)
        if e.method == "len" and not e.args and (heap_kind(ot) == "List" or is_array_type(ot) or is_slice_type(ot)):
            friendly.as_len_field(e)  # `xs.len()` and `xs.len` are the same length
            return "usize"
        if e.method == "drop" and self._has_user_drop(ot):
            self._err(e, f"`drop` of `{ot}` runs by itself when the value goes away; it cannot be called.",
                      "Let the owner go out of scope, or move the value into a function that ends.",
                      rule="drop-misuse", details={"type": ot})
            self._eval_args_quietly(e.args)
            return VOID
        if e.method == "clone" and self._builtin_clone(e, ot):
            return ot
        if heap_kind(ot) == "List":
            return self._vec_method(e, ot)
        if heap_kind(ot) in ("Box", "Shared", "Arc"):
            self._err(e, f"Type `{ot}` has no methods.", "Access inner value with `.value`.")
            self._eval_args_quietly(e.args)
            return ERR
        if ot == "str":
            if e.method == "to_string":
                if e.args:
                    self._err(e, "`str.to_string()` takes no arguments.")
                e.owner = "str"
                return "string"
            if e.method == "len":
                if e.args:
                    self._err(e, "`str.len()` takes no arguments.")
                e.owner = "str"
                return "usize"
        info = self.funcs.get(f"{ot}.{e.method}") or self._method_template_info(ot, e.method, e)
        if info is not None and not self._is_visible(info.decl) and not self._is_type_arg(ot):
            self._err(e, f"`{e.method}` is private.",
                      f"Put `{e.method}` under a `public` line in its module.")
            self._eval_args_quietly(e.args)
            return ERR
        if info is None and e.method == "to_string" and not e.args and self._show_problem(ot) is None:
            _replace(e, _at(FormatStr([e.obj]), e))  # `p.to_string()`: the text `print(p)` writes
            return self._format_str(e)  # type: ignore[arg-type]
        if info is None and int_base(ot) == "string" and f"str.{e.method}" in self.funcs:
            e.obj = _at(MethodCall(e.obj, "as_str", []), e.obj)  # `s.trim()` on a `string`: the `str` method
            return self._method_call(e, expected)
        if info is None and ot in self.structs and self.structs[ot].fields.get(e.method, "") in self.closures:
            fa = FieldAccess(e.obj, e.method)
            fa.line, fa.col, fa.length = e.line, e.col, e.length
            fa.filename = getattr(e, "filename", None)
            closure = self._expr(fa)
            return self._closure_call(e, fa, closure)
        if info is None and ot in self.structs and (is_fn_type(self.structs[ot].fields.get(e.method, ""))
                                                    or is_boxed_fn(self.structs[ot].fields.get(e.method, ""))):
            fa = FieldAccess(e.obj, e.method)  # `s.callback(x)`: call through a function pointer field
            fa.line, fa.col, fa.length = e.line, e.col, e.length
            fa.filename = getattr(e, "filename", None)
            fty = self._expr(fa)
            return self._indirect_call(e, fa, fty, f"{unparse(e.obj)}.{e.method}", e.args)
        if info is None:
            base = (generic_parts(ot) or (ot, []))[0]
            methods = [k.split(".", 1)[1] for k in list(self.funcs) + list(self.method_templates)
                       if k.startswith((ot + ".", base + "."))]
            hint = f"`{ot}` methods: {', '.join(methods)}." if methods else \
                f"You can define it in `impl {ot}:` as `fn {e.method}(self):`."
            extra = ["len", "to_string"] if ot == "str" else []
            self._err(e, f"Type `{ot}` has no method named `{e.method}`.", hint,
                      fixes=self._member_fix(e, e.method, methods + extra))
            for a in e.args:
                self._expr_any(a)
            return ERR
        e.owner = ot
        receiver_access: ArgAccess | None = None
        if info.params[0].mode == "read":
            e.self_lend = True
            e.self_mode = "read"
            receiver_access = ArgAccess("read", self._path(e.obj), ot, e.obj, e.obj, is_receiver=True)
        elif info.params[0].mode == "lend":
            e.self_lend = True
            e.self_mode = "lend"
            path = _place_path(e.obj)
            if getattr(e.obj, "view_lend", False):
                pass  # the receiver is a `lend T` returned by a call
            elif path is None:
                self._err(e.obj, f"`{e.method}` is a mutating method; receiver must be a variable (or field).",
                          "Assign the value to a variable first.")
            elif self._check_mutable(e.obj, "method", e.method):
                receiver_access = ArgAccess("lend", self._path(e.obj), ot, e.obj, e.obj, is_receiver=True)
        else:
            path = _place_path(e.obj)
            receiver_access = ArgAccess(info.params[0].mode or "val", self._path(e.obj), ot, e.obj, e.obj, is_receiver=True)
            if info.params[0].mode == "consume" and self._moves(ot) and self._is_place_expr(e.obj):
                if self._check_move(e.obj, e.obj):  # `x.into_parts()`: the call takes `x`
                    e.obj.is_move = True  # type: ignore[attr-defined]
        spec = self._specialize_for_closures(info, e.args, e, offset=1)
        if spec is not info:
            e.method_key = spec.key  # type: ignore[attr-defined]
            info = spec
        self._check_args(e, f"{unparse(e.obj)}.{e.method}", info.params[1:], e.args, receiver_access)
        self._mark_view(e, info)
        return info.ret

    def _tuple_lit(self, e: StructLit, expected: str | None) -> str:
        """`(a, b)`: element types come from the expected tuple type or from the values themselves."""
        n = len(e.fields)
        exp_args: list[str] | None = None
        gp = generic_parts(expected) if expected else None
        if gp and gp[0] == f"Tuple{n}" and len(gp[1]) == n:
            exp_args = gp[1]
        tys: list[str] = []
        for i, fi in enumerate(e.fields):
            exp = exp_args[i] if exp_args else None
            vt = self._expr(fi.value, exp)
            if exp is not None:
                self._expect_type(exp, vt, fi.value)
                vt = exp if vt != ERR else vt
            self._no_implicit_copy(fi.value, vt)
            tys.append(vt)
        if ERR in tys:
            return ERR
        refs = []
        for t in tys:
            r = TypeRef(t)
            r.resolved = t  # type: ignore[attr-defined]
            r.line, r.col, r.length = e.line, e.col, e.length
            refs.append(r)
        e.type_args = refs
        canon = self._resolve_app(e.type_name, refs, e)
        return canon

    def _struct_lit(self, e: StructLit, expected: str | None = None) -> str:
        if getattr(e, "is_tuple", False):
            return self._tuple_lit(e, expected)
        info, handled = self._struct_lit_info(e, expected)
        if info is None:
            if not handled:
                near = difflib.get_close_matches(e.type_name, list(self.structs), n=1)
                self._err(e, f"Unknown struct `{e.type_name}`.",
                          f"Did you mean: `{near[0]}`?" if near else None)
            for fi in e.fields:
                self._expr_any(fi.value)
            return ERR
        seen: set[str] = set()
        for fi in e.fields:
            fty = info.fields.get(fi.name)
            if fty is None:
                self._err(fi, f"Struct `{info.name}` has no field named `{fi.name}`.",
                          f"Fields: {', '.join(info.fields)}.")
                self._expr_any(fi.value)
                continue
            if fi.name in seen:
                self._err(fi, f"Field `{fi.name}` provided twice.")
            seen.add(fi.name)
            if not self._field_ok(info, fi.name, fi):
                self._expr_any(fi.value)
                continue
            vt = self._expr(fi.value, fty)
            fmode = info.field_modes.get(fi.name)
            self._expect_type(fty, vt, fi.value, widen=not fmode)
            if fmode:
                if not self._is_place_expr(fi.value):
                    self._err(fi.value, f"`{fi.name}` is a reference field; variable or field must be provided.",
                              "Assign value to a variable first, then pass.")
                elif fmode == "lend":
                    self._check_mutable(fi.value, "lend")
                fi.ref_mode = fmode
            else:
                self._no_implicit_copy(fi.value, fty)
        missing = [n for n in info.fields if n not in seen]
        if getattr(info.decl, "is_union", False):
            if len(seen) != 1:
                self._err(e, f"A `{info.name}` union value sets exactly one field.",
                          f"Write `{info.name}{{ {next(iter(info.fields))}: ... }}`.")
            return info.name
        if missing:
            self._err(e, f"Missing field(s) in `{info.name}` value: {', '.join(missing)}.",
                      "Every field gets a value in the literal.", fixes=self._missing_field_fix(e, info, missing))
        return info.name

    def _missing_field_fix(self, e: StructLit, info: StructInfo, missing: list[str]) -> list[Fix]:
        values = [(n, friendly.zero_value(info.fields[n])) for n in missing]
        if any(v is None for _n, v in values) or not e.fields:
            return []
        last = e.fields[-1].value
        end = friendly.span_end(last)
        if end is None:
            return []
        text = "".join(f", {n}: {v}" for n, v in values)
        return [Fix(f"Add {', '.join(f'`{n}`' for n in missing)} with a starting value", "likely",
                    [Edit(end[0], end[1], end[0], end[1], text, getattr(e, "filename", None))])]

    def _infer_struct_args(self, e: StructLit, decl: StructDecl, expected: str | None) -> list[str] | None:
        """`Pair{ first: 1, second: "a" }` is `Pair[i32, str]`: read each type parameter off a field value."""
        params = list(decl.type_params)
        if expected:
            parts = generic_parts(expected)
            if parts and parts[0] == e.type_name and len(parts[1]) == len(params):
                return list(parts[1])
        found: dict[str, str] = {}
        by_name = {f.name: f.type_ref for f in decl.fields}
        mark = len(self.diags.items)
        try:
            for fi in e.fields:
                tref = by_name.get(fi.name)
                if tref is None:
                    continue
                self._bind_type_params(tref, self._expr_any(copy.deepcopy(fi.value)), params, found)
        finally:
            del self.diags.items[mark:]  # the real check of each field comes next, with the inferred types
        if any(p not in found or found[p] == ERR for p in params):
            return None
        return [found[p] for p in params]

    def _bind_type_params(self, tref: TypeRef, actual: str, params: list[str], found: dict[str, str]) -> None:
        if actual == ERR:
            return
        if tref.name in params and not tref.args:
            found.setdefault(tref.name, actual)
            return
        if getattr(tref, "is_array", False) and is_array_type(actual):  # `[W]T` gives `W` its length
            size = tref.size_expr
            n, elem = array_info(actual)
            if isinstance(size, Name) and size.name in params:
                found.setdefault(size.name, str(n))
            if tref.elem is not None:
                self._bind_type_params(tref.elem, elem, params, found)
            return
        if getattr(tref, "is_slice", False) and tref.elem is not None and is_slice_type(actual):
            self._bind_type_params(tref.elem, slice_elem_type(actual), params, found)
            return
        parts = generic_parts(actual)
        base = tref.base or tref.name
        if tref.args and parts and parts[0] == base and len(parts[1]) == len(tref.args):
            for sub, sub_actual in zip(tref.args, parts[1]):
                self._bind_type_params(sub, sub_actual, params, found)

    def _struct_lit_info(self, e: StructLit, expected: str | None = None) -> tuple[StructInfo | None, bool]:
        """Resolves type of struct literal. Returns (info, error_already_reported)."""
        type_name = e.type_name
        if e.qualifier:
            found = self._qualified_item(e.qualifier, e.type_name, e)
            if found is False or found is None:
                if found is None:
                    self._err(e, f"Unknown module `{e.qualifier}`.",
                              f"Import it in this file: `import {e.qualifier}`.")
                return None, True
            type_name = found
        else:
            simple = self._resolve_simple(e.type_name)
            if simple is not None:
                type_name = simple
        e.type_name = type_name
        generic = self.generic_structs.get(type_name)
        if generic is not None:
            if not e.type_args:
                args = self._infer_struct_args(e, generic, expected)
                if args is None:
                    self._err(e, f"Generic type `{e.type_name}` must be written explicitly in struct literal.",
                              f"The fields do not show every type argument. Write `{make_generic(e.type_name, generic.type_params)}{{ ... }}`.")
                    return None, True
                canon = self._instantiate_type(type_name, args, e)
                return self.structs.get(canon), True
            canon = self._resolve_app(e.type_name, e.type_args, e)
            return self.structs.get(canon), True
        if e.type_args:
            self._err(e, f"`{e.type_name}` is not a generic type, cannot take type arguments.")
            return None, True
        return self.structs.get(e.type_name), False

    # -- call arguments and modes ----------------------------------
    def _check_args(self, node: Call | MethodCall, display: str, params: list[ParamInfo],
                    args: list[Expr], receiver_access: ArgAccess | None = None) -> None:
        if len(args) != len(params):
            sig = ", ".join(f"{'' if p.mode in ('', 'val') else p.mode + ' '}{p.name + ': ' if p.name else ''}{p.ty}"
                            for p in params)
            self._err(node, f"`{display}` expects {len(params)} argument(s), found {len(args)}.",
                      f"Signature: {display}({sig})")
            for a in args:
                self._expr_any(a)
            return

        node.param_tys = [p.ty for p in params]
        node.arg_modes = [("" if p.mode == "val" else p.mode) for p in params]
        accesses: list[ArgAccess] = []
        if receiver_access is not None:
            accesses.append(receiver_access)

        for idx, (arg, p) in enumerate(zip(args, params)):
            mode = "" if p.mode == "val" else p.mode
            if isinstance(arg, SliceExpr):
                arg.in_call_arg = True
            ty = self._expr(arg, p.ty)
            is_copy = False  # in generic code with copyable type `consume`: copy, not move
            if mode == "consume":
                if ty in PRIMS or (is_array_type(ty) and array_info(ty)[1] in PRIMS):
                    if p.generic or (self.cur is not None and self.cur.is_instance):
                        is_copy = True
                if is_slice_type(ty):
                    self._err(arg, "Slice cannot be moved.", "Slice ownership cannot be transferred.")
                    continue
            self._expect_type(p.ty, ty, arg, widen=mode != "lend")
            if p.node is not None and getattr(p.node, "send", False) and ty != ERR:
                # what arrives is the parameter's type (`"one"` becomes a `string`), unless a function
                # or a lambda is being boxed into a `Fn`: then its captures are what crosses
                self._check_send(arg, ty if ty in self.closures or is_fn_type(ty) else p.ty)
            if mode == "lend":
                if not self._check_mutable(arg, "lend"):
                    self._note_inferred(p, display)
                    continue
            elif mode == "consume" and not is_copy and (self._moves(p.ty) or p.ty not in PRIMS):
                fresh = not self._is_place_expr(arg)
                if not fresh and self._check_move(arg, arg):
                    arg.is_move = True
            elif mode == "read" and not self._is_place_expr(arg) and not isinstance(arg, (IntLit, FloatLit, BoolLit, StrLit, CharLit)) and not self._moves(ty):
                pass  # temporary value: codegen emits a temporary address
            if is_copy:
                arg.is_copy = True

            path = self._path(arg)
            is_view = ty == "str" or is_slice_type(ty)
            if is_view and mode in ("", "read") and not is_copy:
                # A `str` or a slice points into the memory it was made from: it reads that place, whether the
                # argument is `s[0..1]`, `s.as_str()`, or `s.trim()`. A `lend` of the same place in this call
                # could move that memory (`s.append_str(s.as_str())` grows `s` while it copies from it).
                sources = [path] if path is not None else self._view_paths(arg)
                for sp in sources:
                    accesses.append(ArgAccess("read", sp, ty, arg, arg))
                if path is not None or sources:
                    continue
            accesses.append(ArgAccess("val" if (is_copy or mode == "") else mode, path, ty, arg, arg))

        self._check_aliases(accesses)

    def _view_paths(self, e: Expr) -> list[tuple[str, ...]]:
        """The places a `str` or slice built right here points into: the receiver and the arguments of the
        calls it is made from (`s.as_str()`, `p.name.trim()`, `first(a, b)`), however deeply nested."""
        ety = getattr(e, "ty", None)
        if not (ety == "str" or is_slice_type(ety or "")):
            return []  # a fresh owned value (`s.clone()`) does not point into what it was made from
        if isinstance(e, SliceExpr):  # `s[0..1]` of a `string` is `s.as_str()[0..1]`
            p = self._path(e.obj)
            return [p] if p is not None else self._view_paths(e.obj)
        if not isinstance(e, (MethodCall, Call)):
            return []
        out: list[tuple[str, ...]] = []
        for part in ([e.obj] if isinstance(e, MethodCall) else []) + list(e.args):
            pty = getattr(part, "ty", None)
            p = self._path(part)
            if p is not None and (pty == "str" or is_slice_type(pty or "") or self._moves(pty or "")
                                  or heap_kind(pty or "") is not None):
                out.append(p)
            elif p is None:
                out += self._view_paths(part)
        return out

    # -- dynamic dispatch: `dyn Feature` ----------------------------------------------------------
    def _dyn_into(self, expected: str, actual: str, node: Node) -> bool:
        """A `T` where a `dyn F` is expected: `T` must satisfy `F` and own everything it holds."""
        fkey = dyn_feature(expected)
        shown = expected.replace("::", ".")
        probs = self._feature_problems(actual, fkey)
        if probs:
            self._err(node, f"`{actual}` cannot be a `{shown}`: " + "; ".join(p.rstrip(".") for p in probs) + ".",
                      f"Give `{actual}` the methods of `{fkey.split('::')[-1]}`.")
            return False
        view = self._view_inside(actual)
        if view is not None:
            self._err(node, f"`{actual}` cannot be a `{shown}`: it holds {view}, and a `dyn` value owns what it holds.",
                      "Store owned data (`string` instead of `str`) in the type, or pass the value as a generic `T` instead.")
            return False
        feat = self.features[fkey]
        for m in feat.methods:  # each method must exist on `actual`, and not take `self` away from the box
            if not m.params or m.params[0].name != "self":
                continue
            base = (generic_parts(actual) or (actual, []))[0]
            info = self.funcs.get(f"{actual}.{m.name}")
            if info is None and f"{base}.{m.name}" in self.method_templates:
                info = self._method_template_info(actual, m.name, node)
            if info is not None and info.params and info.params[0].mode == "consume":
                self._err(node, f"`{actual}.{m.name}` takes `self` as `consume`, so it cannot be called through `{shown}`.",
                          "Take `self` as `read` or `lend` in that method.")
                return False
        if self._moves(actual) and self._is_place_expr(node):  # the value moves into the `dyn` box
            if not self._check_move(node, node):  # type: ignore[arg-type]
                return False
            node.is_move = True  # type: ignore[attr-defined]
        node.box_fn = expected  # type: ignore[attr-defined]
        node.dyn_from = actual  # type: ignore[attr-defined]
        return True

    def _view_inside(self, ty: str, seen: frozenset[str] = frozenset()) -> str | None:
        """A view (`str`, slice, reference field) held by value inside `ty`, described, or None."""
        if ty in seen:
            return None
        if ty == "str":
            return "a `str` view"
        if is_slice_type(ty):
            return f"the slice `{ty}`"
        seen = seen | {ty}
        if heap_kind(ty) is not None and not is_boxed_fn(ty):
            return self._view_inside(heap_inner(ty), seen)
        if is_array_type(ty):
            return self._view_inside(array_info(ty)[1], seen)
        info = self.structs.get(ty)
        if info is not None:
            for n, fty in info.fields.items():
                if n in info.field_modes:
                    return f"the reference field `{n}`"
                found = self._view_inside(fty, seen)
                if found:
                    return found
        einfo = self.enums.get(ty)
        if einfo is not None:
            for v in einfo.variants.values():
                for pt in v.payload:
                    found = self._view_inside(pt, seen)
                    if found:
                        return found
        return None

    def _dyn_method_call(self, e: MethodCall, ot: str) -> str:
        """`shape.area()` on a `dyn Shape`: a call through the value's table of methods."""
        fkey = dyn_feature(ot)
        feat = self.features[fkey]
        shown = ot.replace("::", ".")
        found = next(((i, m) for i, m in enumerate(feat.methods) if m.name == e.method), None)
        if found is None:
            near = difflib.get_close_matches(e.method, [m.name for m in feat.methods], n=1)
            self._err(e, f"`{shown}` has no method named `{e.method}`.",
                      f"Did you mean `{near[0]}`?" if near else
                      f"Methods of `{fkey.split('::')[-1]}`: {', '.join(m.name for m in feat.methods)}.")
            self._eval_args_quietly(e.args)
            return ERR
        index, m = found
        if not m.params or m.params[0].name != "self" or m.params[0].mode == "consume" or m.ret_view:
            why = ("it has no `self`" if not m.params or m.params[0].name != "self" else
                   "it takes `self` as `consume`" if m.params[0].mode == "consume" else "it returns a reference")
            self._err(e, f"`{e.method}` cannot be called through `{shown}`: {why}.",
                      "Call it on the concrete type, or change the feature method.")
            self._eval_args_quietly(e.args)
            return ERR
        params: list[ParamInfo] = []
        for p in m.params[1:]:
            ty = self._signature_type(p.type_ref, feat, "__no_self__")
            if ty == ERR or "__no_self__" in ty:
                self._err(e, f"`{e.method}` cannot be called through `{shown}`: parameter `{p.name}` mentions `Self`.",
                          "Through `dyn`, the concrete type is not known; call it on the concrete type.")
                self._eval_args_quietly(e.args)
                return ERR
            if self._moves(ty) and p.mode in ("", "consume"):
                self._err(e, f"`{e.method}` cannot be called through `{shown}`: parameter `{p.name}` takes a moved `{ty}`.",
                          f"Write the parameter as `{p.name}: read {ty}` or `lend {ty}` in the feature.")
                self._eval_args_quietly(e.args)
                return ERR
            if is_slice_type(ty) and getattr(p, "exclusive", False):
                self._err(e, f"`{e.method}` cannot be called through `{shown}`: `exclusive` slice parameter.")
                self._eval_args_quietly(e.args)
                return ERR
            params.append(ParamInfo(p.name, ty, p.mode or "val", p))
        ret = self._signature_type(m.ret, feat, "__no_self__") if m.ret is not None else VOID
        if "__no_self__" in ret:
            self._err(e, f"`{e.method}` cannot be called through `{shown}`: it returns `Self`.",
                      "Through `dyn`, the concrete type is not known; call it on the concrete type.")
            self._eval_args_quietly(e.args)
            return ERR
        if m.params[0].mode == "lend" and not self._check_mutable(e.obj, "lend"):
            self._eval_args_quietly(e.args)
            return ERR
        self._check_args(e, f"{shown}.{e.method}", params, e.args, None)
        e.owner = ot
        e.dyn_index = index  # type: ignore[attr-defined]
        e.self_mode = m.params[0].mode or "read"
        return ret

    def _check_send(self, arg: Expr, ty: str) -> None:
        """`arg` goes to another thread (a `send` parameter): everything it carries must be safe there."""
        reason = None
        info = self.structs.get(ty)
        if ty in self.closures and info is not None:  # a lambda written at the call: check what it captures
            for name, fty in info.fields.items():
                why = (f"it borrows `{name}`" if name in info.field_modes
                       else thread_problem(fty, self.structs, self.enums))
                if why:
                    reason = f"the lambda captures `{name}`: {why}"
                    break
        else:
            reason = thread_problem(ty, self.structs, self.enums)
        if reason:
            shown = "This lambda" if ty in self.closures else f"`{unparse(arg)}`"
            self._err(arg, f"{shown} cannot go to another thread: {reason}.",
                      "Move owned data into the thread (`string`, `List`), or share it read-only with `Arc`.",
                      rule="not-send", details={"value": unparse(arg), "reason": reason})

    def _check_aliases(self, accesses: list[ArgAccess]) -> None:
        """Borrow rule: `lend` is exclusive for the same memory; no `read`/`consume` while `lend` is active."""
        reported: set[int] = set()
        for i in range(len(accesses)):
            for j in range(i + 1, len(accesses)):
                acc1 = accesses[i]
                acc2 = accesses[j]
                if id(acc2.node) in reported:
                    continue
                if acc1.path is None or acc2.path is None:
                    continue
                if not _overlap(acc1.path, acc2.path):
                    continue

                modes = {acc1.mode, acc2.mode}
                if "lend" not in modes:
                    continue
                if acc1.mode == "lend" and acc2.mode == "lend":
                    if unparse(acc1.target) == unparse(acc2.target):
                        msg = f"`{unparse(acc2.target)}` cannot be borrowed as `lend` multiple times in the same call."
                    else:
                        msg = f"`{unparse(acc2.target)}` and `{unparse(acc1.target)}` cannot be borrowed as `lend` in the same call (conflicting memory access)."
                    hint = "Cannot grant two mutating accesses to the same data simultaneously; split the call in two."
                    rule = "double-lend"
                elif "consume" in modes:
                    consume_acc = acc1 if acc1.mode == "consume" else acc2
                    msg = f"`{unparse(consume_acc.target)}` cannot be borrowed as `lend` while being moved (`consume`)."
                    hint = "Borrow before moving or split the call in two."
                    rule = "lend-while-consume"
                elif "read" in modes:
                    msg = f"`{unparse(acc1.target if acc1.mode == 'read' else acc2.target)}` cannot be borrowed as both `read` and `lend` at the same time (risk of data race)."
                    hint = "No other `read` allowed while `lend` is active; split the call."
                    rule = "lend-while-read"
                else:  # "val" + lend
                    val_acc = acc1 if acc1.mode == "val" else acc2
                    if val_acc.ty == ERR or val_acc.ty in PRIMS:
                        continue
                    msg = f"`{unparse(val_acc.target)}` is both borrowed as `lend` and read (aliasing risk)."
                    hint = "`copy` value to a local variable before call or split the call."
                    rule = "lend-alias"
                self._alias_err(acc1, acc2, msg, hint, rule, modes)
                reported.add(id(acc2.node))

    def _alias_err(self, acc1: ArgAccess, acc2: ArgAccess, msg: str, hint: str, rule: str, modes: set[str]) -> None:
        note_txt = "receiver is here" if acc1.is_receiver else "first access is here"
        note = Note(acc1.node.line, acc1.node.col, acc1.node.length, note_txt)
        labels = [Label("cause", f"`{unparse(acc1.target)}` is used here", acc1.node.line, acc1.node.col,
                        max(acc1.node.length, 1), getattr(acc1.node, "filename", None))]
        for acc in (acc1, acc2):
            root = self._root_var(acc.target)
            labels += self._def_label(root, f"`{root.name}` is declared here" if root else "")
        self._err(acc2.node, msg, hint, notes=[note], rule=rule, labels=labels,
                  details={"left": unparse(acc1.target), "right": unparse(acc2.target), "modes": sorted(modes)},
                  fixes=[Fix("Split the call so the `lend` does not overlap another access to the same value", "manual", [])])

    def _check_move(self, target: Expr, arg: Expr) -> bool:
        """`target` is a heap-owning place: can ownership be moved? Errors and returns False if cannot."""
        if getattr(target, "is_view", False):
            self._err(arg, f"`{unparse(target)}` is a view (`ref`); view ownership cannot be moved.",
                      "Views are read-only.", rule="cannot-move", details={"value": unparse(target)})
            return False
        if isinstance(target, IndexAccess):
            ety = getattr(target, "ty", None)
            clonable = not (isinstance(ety, str) and held_handle(ety, self.structs, self.enums) is not None)
            pop = ", or take the element out with `pop()`" if heap_kind(getattr(target.obj, "ty", "") or "") == "List" else ""
            self._err(arg, f"`{unparse(target)}` cannot be moved out: the element belongs to `{unparse(target.obj)}`.",
                      (f"Move a copy with `{unparse(target)}.clone()`{pop}." if clonable
                       else f"Use it in place (`{unparse(target)}.method()`){pop}."),
                      rule="cannot-move", details={"value": unparse(target)},
                      fixes=friendly.wrap_fix(target, "", ".clone()", f"Move a copy: `{unparse(target)}.clone()`")
                      if clonable else [])
            return False
        if isinstance(target, SliceExpr):
            self._err(arg, "Slice cannot be moved.", "Slice ownership cannot be transferred.",
                      rule="cannot-move", details={"value": unparse(target)})
            return False
        ty = getattr(target, "ty", None)
        shared = self._through_shared(target)
        if shared is not None and isinstance(ty, str) and self._moves(ty):
            self._err(arg, f"`{unparse(target)}` cannot be moved out of the `{self._shared_kind(target)}` value `{shared}`.",
                      f"Take a copy with `{unparse(target)}.clone()`, or share it further with `{shared}.clone()`.",
                      rule="cannot-move", details={"value": unparse(target)},
                      fixes=friendly.wrap_fix(target, "", ".clone()", f"Take a copy: `{unparse(target)}.clone()`"))
            return False
        if isinstance(ty, str) and self._moves(ty) and isinstance(target, FieldAccess):
            self._err(arg, f"`{unparse(target)}` cannot be moved: heap-owning fields cannot be moved alone (no partial moves).",
                      "Move the entire variable or mutate by reassigning the field.",
                      rule="partial-move", details={"value": unparse(target)},
                      labels=self._def_label(self._root_var(target), "the owner is declared here"))
            return False
        root = self._root_var(target)
        if root is not None and root.kind == "val" and isinstance(ty, str) and not self._moves(ty):
            return True  # a by-value parameter of a copyable type is the function's own copy
        if root is not None and root.kind in ("read", "lend") and self._infer_mode(root, "consume"):
            return True
        if root is not None and root.kind in ("val", "read", "lend"):
            what = {"val": "value", "read": "`read` (read-only)", "lend": "borrowed (`lend`)"}[root.kind]
            self._err(arg, f"`{unparse(target)}` cannot be moved: `{root.name}` is a {what} parameter, you do not own it.",
                      f"To take ownership, make parameter `{root.name}: consume Type`.",
                      rule="move-of-borrow",
                      labels=self._def_label(root, f"`{root.name}` is declared here"),
                      details={"value": unparse(target), "kind": root.kind})
            return False
        return True


# ======================================================================
# Move analysis
# ======================================================================

@dataclass
class _Moved:
    line: int
    col: int
    length: int
    callee: str | None = None
    param: str | None = None
    mode_span: tuple[int, int, int] | None = None  # line, col, length of `consume` plus the following space
    filename: str | None = None
    ty: str | None = None  # type of the moved value
    loop_carried: bool = False  # reached the loop head through the back edge: moved by an earlier iteration
    root_decl: object = None  # the moved variable's declaration (for the loop diagnostic)


MoveState = dict[str, _Moved]  # moved path ("a" or "a.b") -> where it was consumed


def _through_index(e: Expr) -> bool:
    while isinstance(e, (IndexAccess, FieldAccess)):
        if isinstance(e, IndexAccess):
            return True
        e = e.obj
    return False


def _path_str(e: Expr) -> str | None:
    p = _place_path(e)
    return None if p is None else ".".join(p)


class MoveAnalyzer:
    """Catches subsequent uses of moved (`consume`/implicit move) values.

    A forward "maybe moved" dataflow over the structured control flow graph: it carries the set of
    paths that may have been moved on some path to this point (`MoveState`), and merges by union.
      * `if/elif/else` and `match`: a value moved in any branch is maybe-moved afterwards
        (a branch ending in `return`/`panic` contributes nothing; `break`/`continue` go to their loop).
      * Loops run to a fixpoint: the state at the loop head is the entry state merged with the state at
        the end of the body and at each `continue`, so a move reaches the next iteration. The state
        after the loop merges the head (condition false) with each `break`. A variable moved in the body
        and reassigned before the next iteration is therefore fine; one used again is an error.
      * Reassignment (`x = ...`) makes the variable usable again.
    Path logic: if `a.b` is moved, `a.b` and `a.b.c` cannot be used; `a` as a whole
    cannot be used (partially moved), but `a.c` can be used.
    """

    def __init__(self, program: Program, diags: DiagnosticBag) -> None:
        self.program = program
        self.diags = diags
        self.loops: list[dict] = []  # innermost last: {"breaks": [MoveState], "continues": [MoveState]}
        # `defer`s of the blocks being analyzed, innermost block last: (the statement, the paths it moves itself).
        # They run when their block ends, however it ends, so what they read must still be there then.
        self.defers: list[list[tuple[Defer, set[str]]]] = []
        self.inst_note: Note | None = None  # "instantiated with" note attached to errors in generic instances
        self.reported: set[tuple[int, int, str]] = set()
        self.bound: dict[str, Node] = {}
        self._ctx: tuple | None = None  # (callee, owner, arg index, FuncDecl | None, is_method)

    def run(self) -> None:
        # Templates themselves are skipped; only concrete functions and generic instances are analyzed.
        self.run_on(list(self.program.decls) + list(self.program.func_instances))

    def run_on(self, decls: list) -> None:
        for d in decls:
            if isinstance(d, FuncDecl) and not d.type_params and not d.owner_params:
                self.current_filename = getattr(d, "filename", None)
                self.loops = []
                self.defers = []
                self.inst_note = d.inst_note
                self.bound = {p.name: p for p in d.params}
                self._ctx = None
                self._block(d.body, {})

    def _error(self, msg: str, line: int, col: int, length: int, hint: str | None,
               notes: list[Note] | None = None, *, rule: str | None = None,
               labels: list[Label] | None = None, details: dict | None = None,
               fixes: list[Fix] | None = None) -> None:
        key = (getattr(self, "current_filename", None), line, col, msg)
        if key in self.reported:
            return
        self.reported.add(key)
        all_notes = list(notes or []) + ([self.inst_note] if self.inst_note is not None else [])
        self.diags.error(msg, line, col, length, hint, all_notes, filename=getattr(self, "current_filename", None),
                         rule=rule, labels=labels, details=details, fixes=fixes)

    # -- statements ------------------------------------------------------
    def _block(self, stmts: list[Stmt], state: MoveState) -> MoveState | None:
        """Runs block; returns None if block terminates on all paths (return/break)."""
        cur: MoveState | None = state
        self.defers.append([])
        try:
            for s in stmts:
                if cur is None:
                    break  # unreachable code
                cur = self._stmt(s, cur)
            if cur is not None:
                self._run_defers(self.defers[-1], cur)  # the block ends normally: its defers run now
        finally:
            self.defers.pop()
        return cur

    def _run_defers(self, entries: list[tuple[Defer, set[str]]], state: MoveState) -> None:
        """Checks the deferred statements against the state where they run (innermost block's last first)."""
        for d, own in reversed(entries):
            at_exit = {k: v for k, v in state.items() if k not in own}  # what the defer moves itself is its own
            self._stmt(d.stmt, at_exit)

    def _run_all_defers(self, state: MoveState, depth: int = 0) -> None:
        """An early exit (`return`, `?`, or `break` out to `depth`) runs the defers of every block it leaves."""
        for entries in reversed(self.defers[depth:]):
            self._run_defers(entries, state)

    def _stmt(self, s: Stmt, state: MoveState) -> MoveState | None:
        if isinstance(s, VarDecl):
            self._expr(s.value, state)
            for k in [k for k in state if k.split(".")[0] == s.name]:
                del state[k]  # new variable: old move state invalidated
            self.bound[s.name] = s
            return state
        if isinstance(s, Assign):
            self._assign(s, state)
            return state
        if isinstance(s, ExprStmt):
            self._expr(s.expr, state)
            return None if is_panic_stmt(s) else state  # panic: path ends
        if isinstance(s, Return):
            if s.value is not None:
                self._expr(s.value, state)
            self._run_all_defers(dict(state))
            return None
        if isinstance(s, (Break, Continue)):
            if self.loops:
                self.loops[-1]["breaks" if isinstance(s, Break) else "continues"].append(dict(state))
                self._run_all_defers(dict(state), self.loops[-1].get("defer_depth", len(self.defers)))
            return None
        if isinstance(s, If):
            return self._if(s, state)
        if isinstance(s, While):
            forever = isinstance(s.cond, BoolLit) and s.cond.value
            return self._loop(s, state, lambda st: self._expr(s.cond, st), [], exits_at_head=not forever)
        if isinstance(s, For):
            self._expr(s.start, state)
            self._expr(s.end, state)
            return self._loop(s, state, None, [s.var])
        if isinstance(s, ForIn):
            self._expr(s.iterable, state)
            return self._loop(s, state, None, [s.var] + ([s.index_var] if s.index_var else []))
        if isinstance(s, Match):
            return self._match(s, state)
        if isinstance(s, Yield):
            self._expr(s.value, state)
        if isinstance(s, Defer):
            before = set(state)
            self._stmt(s.stmt, state)  # conservative: a move is considered to happen at the definition site
            if self.defers:
                self.defers[-1].append((s, set(state) - before))
        return state

    def _loop(self, s: Stmt, state: MoveState, head, bound: list[str], exits_at_head: bool = True) -> MoveState | None:
        """Runs a loop body to a fixpoint of the head state (see the class docstring)."""
        entry: MoveState = dict(state)
        for _ in range(64):  # the state only grows, by paths of this function; this bound is never reached
            ctx: dict = {"breaks": [], "continues": [], "defer_depth": len(self.defers)}
            self.loops.append(ctx)
            at_head = dict(entry)
            if head is not None:
                head(at_head)
            body = dict(at_head)
            for name in bound:  # the loop variables are fresh in each iteration
                for k in [k for k in body if k.split(".")[0] == name]:
                    del body[k]
            end = self._block(s.body, body)  # type: ignore[attr-defined]
            self.loops.pop()
            back = self._merge([end] + ctx["continues"])
            grown = dict(entry)
            for k, mark in (back or {}).items():
                if k not in grown:
                    grown[k] = dc_replace(mark, loop_carried=True)
            if grown.keys() == entry.keys():
                return self._merge(([at_head] if exits_at_head else []) + ctx["breaks"])
            entry = grown
        return self._merge([entry])

    def _match(self, s: Match, state: MoveState) -> MoveState | None:
        """`match` is analyzed like an `if/elif/else` chain (arms are exhaustive: no implicit "none" path)."""
        self._expr(s.scrutinee, state)
        if s.mode == "consume":
            # Regardless of which arm executes, entire scrutinee is considered moved (before arms start).
            self._record_move(s.scrutinee, s.scrutinee, state)
        ends: list[MoveState | None] = []
        for arm in s.arms:
            for name in [b.name for b in arm.bindings] + ([arm.whole] if arm.whole else []):  # new variables
                for k in [k for k in state if k.split(".")[0] == name]:
                    del state[k]
            arm_state = dict(state)
            if arm.guard is not None:
                self._expr(arm.guard, arm_state)
            ends.append(self._block(arm.body, arm_state))
        return self._merge(ends)

    def _if(self, s: If, state: MoveState) -> MoveState | None:
        ends: list[MoveState | None] = []
        for br in s.branches:
            self._expr(br.cond, state)
            ends.append(self._block(br.body, dict(state)))
        if s.else_body is not None:
            ends.append(self._block(s.else_body, dict(state)))
        else:
            ends.append(dict(state))  # none of the branches might execute
        return self._merge(ends)

    @staticmethod
    def _merge(ends: list[MoveState | None]) -> MoveState | None:
        """Merges states at end of branches; None if no branch reaches the end."""
        merged: MoveState = {}
        reachable = False
        for end in ends:
            if end is not None:
                reachable = True
                for k, v in end.items():
                    merged.setdefault(k, v)
        return merged if reachable else None

    def _assign(self, s: Assign, state: MoveState) -> None:
        path = _path_str(s.target)
        self._expr(s.value, state)
        if path is None:
            return
        if s.op != "=" or _through_index(s.target):
            # `a[i] = v` writes into `a` (and drops the old element): it does not give a moved `a` a new value
            self._use_place(s.target, state)
            return
        # Cannot assign to field of a moved parent structure.
        for m in list(state):
            if path.startswith(m + "."):
                self._use_place(s.target, state)
                return
        # Otherwise assignment re-validates this path (and its subpaths).
        for m in list(state):
            if m == path or m.startswith(path + "."):
                del state[m]

    # -- expressions ------------------------------------------------------
    def _expr(self, e: Expr, state: MoveState) -> None:
        if isinstance(e, (Name, FieldAccess)):
            if _path_str(e) is not None:
                self._use_place(e, state)
                if getattr(e, "is_move", False):
                    self._record_move(e, e, state)
            else:
                self._expr(e.obj, state)  # type: ignore[attr-defined]
        elif isinstance(e, Unary):
            self._expr(e.operand, state)
        elif isinstance(e, Binary):
            self._expr(e.left, state)
            self._expr(e.right, state)
        elif isinstance(e, FormatStr):
            for p in e.parts:
                self._expr(p, state)
        elif isinstance(e, Call):
            self._call_args(e.args, state, e.callee, None, False)
        elif isinstance(e, MethodCall):
            self._expr(e.obj, state)
            self._call_args(e.args, state, e.method, e.owner, True)
        elif isinstance(e, Apply):
            self._expr(e.callee, state)
            self._call_args(e.args, state, "", None, False)
        elif isinstance(e, StructLit):
            for f in e.fields:
                self._expr(f.value, state)
        elif isinstance(e, IndexAccess):
            if _path_str(e) is not None:
                self._use_place(e, state)
            self._expr(e.obj, state)
            self._expr(e.index, state)
        elif isinstance(e, SliceExpr):
            if _path_str(e) is not None:
                self._use_place(e, state)
            self._expr(e.obj, state)
            if e.start is not None:
                self._expr(e.start, state)
            if e.end is not None:
                self._expr(e.end, state)
        elif isinstance(e, ArrayLit):
            for el in e.elements:
                self._expr(el, state)
        elif isinstance(e, ArrayRepeatLit):
            self._expr(e.value, state)
            self._expr(e.count, state)
        elif isinstance(e, Cast):
            self._expr(e.expr, state)
        elif isinstance(e, CopyExpr):
            self._expr(e.expr, state)
        elif isinstance(e, BorrowExpr):
            self._expr(e.expr, state)
        elif isinstance(e, BlockExpr):
            end = self._stmt(e.stmt, state)  # arms exhaustive: every path reaches a Yield
            state.clear()
            state.update(end or {})
        elif isinstance(e, Try):
            self._expr(e.operand, state)  # early return path ends like `return`; does not affect continuing path
            self._run_all_defers(dict(state))  # ... and that early return runs the defers of the blocks it leaves

    def _call_args(self, args: list[Expr], state: MoveState, callee: str, owner: str | None, method: bool) -> None:
        func = self._find_func(callee, owner)
        saved = self._ctx
        for i, arg in enumerate(args):
            self._ctx = (callee, owner, i, func, method)
            self._expr(arg, state)
        self._ctx = saved

    def _find_func(self, name: str, owner: str | None) -> FuncDecl | None:
        index = getattr(self, "_func_index", None)
        if index is None:  # (name, owner) -> the first concrete declaration, else the first one
            index = {}
            for d in list(self.program.decls) + list(self.program.func_instances):
                if isinstance(d, FuncDecl):
                    key = (d.name, d.owner)
                    if key not in index or (index[key].type_params and not d.type_params):
                        index[key] = d
            self._func_index = index
        return index.get((name, owner))

    def _moved_from(self, node: Node) -> _Moved:
        mark = _Moved(node.line, node.col, node.length, filename=getattr(node, "filename", None),
                      ty=getattr(node, "ty", None))
        ctx = self._ctx
        if ctx is None:
            return mark
        callee, _owner, index, func, method = ctx
        if func is None:
            return mark
        slot = index + (1 if method and func.params and func.params[0].name == "self" else 0)
        if not 0 <= slot < len(func.params):
            return mark
        param = func.params[slot]
        if param.mode != "consume":
            return mark
        span = None
        if param.mode_length:
            span = (param.mode_line, param.mode_col, param.mode_length)
        return _Moved(node.line, node.col, node.length, callee, param.name, span,
                      getattr(param, "filename", None) or getattr(node, "filename", None))

    def _record_move(self, target: Expr, node: Node, state: MoveState) -> None:
        """Marks path `target` as moved."""
        path = _path_str(target)
        if path is None:
            return
        state[path] = self._moved_from(node)

    def _loop_carried_error(self, root: str, mark: _Moved) -> None:
        """A value moved in a loop body is used again by a later iteration (reported at the move)."""
        decl = self.bound.get(root)
        labels = []
        if decl is not None:
            labels.append(Label("definition", f"`{root}` is declared here", decl.line, decl.col,
                                max(decl.length, 1), getattr(decl, "filename", None)))
        self._error(
            f"`{root}` is defined outside the loop and is moved (`consume`) on each iteration of the loop.",
            mark.line, mark.col, mark.length,
            f"Declare `{root}` inside the loop, move it after the loop, or give it a new value "
            f"(`{root} = ...`) before the next iteration.",
            rule="consume-in-loop", labels=labels,
            details={"value": root, "state": "consumed",
                     "consumed_at": {"line": mark.line, "column": mark.col}},
            fixes=[Fix("Move the consume outside the loop, or declare the variable inside the loop", "manual", [])])

    def _use_place(self, e: Expr, state: MoveState) -> None:
        path = _path_str(e)
        if path is None:
            return
        for m, mark in list(state.items()):
            whole = path == m or path.startswith(m + ".")
            partial = m.startswith(path + ".")
            if not (whole or partial):
                continue
            kind = "field" if "." in m else "variable"
            if mark.loop_carried:
                self._loop_carried_error(m.split(".")[0], mark)
                del state[m]
                continue
            if whole:
                msg = f"`{m}` {kind} was moved (`consume`), can no longer be used."
                rule = "use-after-consume"
            else:
                msg = f"`{path}` cannot be used: field `{m}` was moved (`consume`)."
                rule = "use-after-partial-move"
            root = m.split(".")[0]
            why = ""
            if mark.callee and mark.param:
                why = f": `{mark.callee}` keeps its parameter `{mark.param}`" + (
                    "" if mark.mode_span else " (the body moves it, so the mode is `consume`)")
            labels = [Label("cause", f"`{m}` is consumed here{why}", mark.line, mark.col, mark.length, mark.filename)]
            decl = self.bound.get(root)
            if decl is not None:
                labels.append(Label("definition", f"`{root}` is declared here", decl.line, decl.col,
                                    max(decl.length, 1), getattr(decl, "filename", None)))
            if mark.callee and mark.param:
                labels.append(Label(
                    "expected", f"`{mark.callee}` takes `{mark.param}` as `consume`",
                    mark.mode_span[0] if mark.mode_span else mark.line,
                    mark.mode_span[1] if mark.mode_span else mark.col,
                    mark.mode_span[2] if mark.mode_span else mark.length,
                    mark.filename))
            details: dict = {
                "value": m if whole else path,
                "state": "consumed",
                "consumed_at": {"line": mark.line, "column": mark.col},
                "used_at": {"line": e.line, "column": e.col},
                "callee": mark.callee,
                "parameter": mark.param,
            }
            if not whole:
                details["field"] = m
            fixes: list[Fix] = []
            if mark.mode_span and mark.param:
                line, col, length = mark.mode_span
                fixes.append(Fix(
                    f"Remove `consume` from `{mark.param}` so the caller keeps ownership",
                    "likely",
                    [Edit(line, col, line, col + length, "", mark.filename)],
                ))
            handle = (held_handle(mark.ty, self.program.struct_infos, self.program.enum_infos)
                      if isinstance(mark.ty, str) else None)
            if whole and handle is None:
                at = mark.col + mark.length
                fixes.append(Fix(f"Move a copy instead: `{m}.clone()`", "likely",
                                 [Edit(mark.line, at, mark.line, at, ".clone()", mark.filename)]))
            fixes.append(Fix(f"Use `{root}` before it is consumed, or do not use it afterwards", "manual", []))
            self._error(
                msg, e.line, e.col, e.length,
                (f"`{m}` holds the OS handle `{handle}`, which is moved, not copied. Keep using `{m}` "
                 f"and pass it as `read`/`lend` where it is needed." if whole and handle is not None else
                 f"Move a copy with `{m}.clone()` to keep using `{m}`, use it before the move, "
                 f"or reassign it after the move." if whole else
                 f"Use before moving, or assign `{root}` a new value after moving."),
                [Note(mark.line, mark.col, mark.length, f"`{m}` was moved here (line {mark.line}){why}")],
                rule=rule, labels=labels, details=details, fixes=fixes)
            del state[m]  # do not re-report repeatedly for the same move


def _core_funcs(checker: "TypeChecker") -> dict[str, FuncDecl]:
    """The non-generic functions of the Core library, by key (`name` or `Owner.name`)."""
    core: dict[str, FuncDecl] = {}
    for d in checker.decls:
        if (isinstance(d, FuncDecl) and getattr(d, "from_prelude", False) and not d.type_params
                and not d.owner_params and (d.owner is None or d.owner not in checker.generic_structs
                                            and d.owner not in checker.generic_enums)):
            core[d.name if d.owner is None else f"{d.owner}.{d.name}"] = d
    return core


def _core_refs(root: Node, core: dict[str, FuncDecl]) -> set[str]:
    """Keys of the Core functions `root` calls, directly or through what codegen emits for it."""
    found: set[str] = set()
    stack: list[object] = [root]
    while stack:
        n = stack.pop()
        if isinstance(n, Node):
            if isinstance(n, Call) and n.callee in core:
                found.add(n.callee)
            elif isinstance(n, MethodCall) and n.owner and f"{n.owner}.{n.method}" in core:
                found.add(f"{n.owner}.{n.method}")
            elif getattr(n, "from_fn", None) in core:  # `?` converting the error with `Target.from`
                found.add(n.from_fn)
            if getattr(n, "json_ty", None):  # `to_json` / `from_json`: codegen calls the Core JSON pieces
                found.update(k for k in core if k.startswith(("_json_", "_JsonReader.")))
                found.update(k for k in ("string.new", "string.from", "string.append_str", "string.append_byte",
                                         "string.append_i64", "string.append_u64", "string.append_bool",
                                         "string.append") if k in core)
            if (isinstance(n, FormatStr)
                    or (isinstance(n, Binary) and n.op == "+" and getattr(n, "ty", None) == "string")
                    or getattr(n, "is_string_conv", False)
                    or getattr(n, "needs_show", False)
                    or (isinstance(n, MethodCall) and getattr(n, "owner", "") == "str" and n.method == "to_string")):
                found.update({k for k in ("string.new", "string.from", "string.append_str", "string.append_byte",
                                          "string.append_i64", "string.append_u64", "string.append_bool", "string.append")
                              if k in core})
            stack.extend(v for v in n.__dict__.values() if isinstance(v, (Node, list)))
        elif isinstance(n, list):
            stack.extend(n)
    return found


def _used_core_funcs(program: Program, checker: "TypeChecker") -> list[FuncDecl]:
    """Returns non-generic functions of the Core library that the program (transitively) uses."""
    core = _core_funcs(checker)
    used: dict[str, FuncDecl] = {}
    work: list[Node] = [d for d in program.decls if isinstance(d, (FuncDecl, ConstDecl))] + list(checker.instances)
    while work:
        for key in _core_refs(work.pop(), core):
            if key not in used:
                used[key] = core[key]
                work.append(core[key])
    return list(used.values())


def _eval_comptime(program: Program, diags: DiagnosticBag, checker: "TypeChecker") -> None:
    """Evaluates constants calling `comptime fn` at compile time; result written to `ConstDecl.comptime_value`."""
    from .comptime import ComptimeError, Interp
    interp = Interp(program)
    for d in program.decls:
        if isinstance(d, ConstDecl) and checker._calls_comptime(d.value):
            try:
                d.comptime_value = interp.eval_decl(d)  # type: ignore[attr-defined]
            except ComptimeError as err:
                diags.error(f"comptime evaluation failed: {err}", d.value.line, d.value.col, d.value.length,
                            hint="`comptime fn` can only compute numbers/arrays/structs; cannot use I/O or heap.")
            except RecursionError:
                diags.error("comptime evaluation exceeded maximum recursion depth.", d.value.line, d.value.col,
                            d.value.length)


_MODE_RANK = {"read": 0, "lend": 1, "consume": 2}


def _param_key(p: Param, d: FuncDecl) -> tuple:
    """Identifies a parameter across check passes: source position, plus the instance for generic code."""
    return ("param", bool(getattr(d, "from_prelude", False)), getattr(p, "filename", None), p.line, p.col, p.name,
            getattr(d, "inst_key", None))


def _mark_auto_fixed(program: Program, changes: dict[tuple, bool]) -> None:
    """`x = ...` that nothing changes behaves as `fixed x = ...`; editors show the word as a hint."""
    from .closures import _walk  # local: keep import list of this module unchanged

    roots = list(program.decls) + list(getattr(program, "func_instances", []) or [])
    for n in _walk(roots):
        if isinstance(n, VarDecl) and n.mutable:
            n.auto_fixed = changes.get(TypeChecker._var_key(n)) is False  # type: ignore[attr-defined]


def check_program(program: Program, diags: DiagnosticBag, filename: str = "<source>",
                  require_main: bool = True) -> "TypeChecker":
    """Runs type checking and, if error-free, move analysis.

    A heap-owning parameter written without a mode (`xs: List[i32]`) starts as `read`. When the body
    mutates it, it becomes `lend`; when the body moves it, `consume`. Each upgrade re-checks a pristine
    copy of the program, because callers must see the final signature. Modes only grow, so this ends.
    """
    before = len(diags.items)
    pristine = pickle.dumps(program, protocol=pickle.HIGHEST_PROTOCOL)  # a snapshot, much faster than deepcopy
    modes: dict[tuple, str] = {}
    while True:
        checker = TypeChecker(program, diags, filename, require_main=require_main, inferred=modes)
        checker.check()
        grown = {k: m for k, m in checker.mode_upgrades.items()
                 if _MODE_RANK[m] > _MODE_RANK[modes.get(k, "read")]}
        grown.update({k: t for k, t in checker.none_found.items() if k not in modes})  # `x = None` types
        if not grown:
            break
        modes.update(grown)
        del diags.items[before:]
        program.__dict__.update(pickle.loads(pristine).__dict__)
    program.struct_infos = checker.structs
    program.enum_infos = checker.enums
    program.type_order = checker.type_order
    program.var_changes = checker.var_changes
    program.func_instances = checker.instances + _used_core_funcs(program, checker)
    _mark_auto_fixed(program, checker.var_changes)
    if len(diags.items) == before:
        _eval_comptime(program, diags, checker)
    if len(diags.items) == before:
        run_attribute_handlers(program, diags)
    program.decls[:] = [d for d in program.decls if not getattr(d, "attr_handler", False)]
    if len(diags.items) == before:
        MoveAnalyzer(program, diags).run()
    if len(diags.items) == before:
        from .borrow import check_borrows
        check_borrows(program, diags)
    return checker
