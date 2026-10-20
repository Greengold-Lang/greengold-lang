"""Generic types and functions: instantiation (monomorphization) and type argument inference.

Approach (like C++ templates): a generic definition is stored only as syntax.
For each DISTINCT type argument list:
    * for a generic TYPE, a new struct/enum entry filled with concrete types is created (`Pair[i32, f64]`),
    * for a generic FUNCTION / METHOD, the body is COPIED and type checked like an ordinary function
      while `self.tparams` (T -> i32) is active.
Thus, everything in the body like `a > b`, `T(x)` is checked against concrete types.

A generic body is also checked against its bounds, where it is declared (`_check_against_bounds`), so a
body that uses more than its bounds promise is reported to its author, and an unused generic is checked.
A type parameter with a closed builtin bound (`Num`, `Int`, `Float`, `Ord`, `Eq`) is instantiated with
one type of each kind in that set (`i8`, `u8`, `i64`, `usize`, `f32`, `f64`, `bool`, `str`). Any other
type parameter becomes an archetype: a type that has exactly the methods of its feature bounds.
The check is about what a body may DO with a `T` (methods, operators, conversions). Ownership rules that
depend on the real type (whether `T` is copied or moved) are checked when the generic is used.

This class is a mixin joining `TypeChecker` (see matchcheck.py).
"""
from __future__ import annotations

import copy
import difflib

from .ast_nodes import (
    Binary, Call, Cast, EnumDecl, Expr, FuncDecl, IntLit, FloatLit, MethodCall, Name, Node, SliceExpr,
    StructDecl, StructLit, FeatureDecl, TypeRef, Unary,
)
from .diagnostics import Note
from .typeinfo import (
    TYPE_ALIASES, BUILTIN_TYPE_ALIASES,
    BUILTINS, ERR, EnumInfo, FLOATS, FuncInfo, HEAP_BUILTINS, INTS, INT_RANGES, NUMERIC, PRELUDE_NAMES, PRIMS, StructInfo,
    array_info, func_cname, generic_parts, is_array_type, is_const_expr, is_slice_type, make_generic, mangle,
    slice_elem_type, fn_parts, is_fn_type, is_boxed_fn, int_base, is_const_arg,
)

# `fn f[N: usize]`: a constant parameter's body is checked once, with this value standing in for `N`.
CONST_REPRESENTATIVE = "4096"


def const_param_type(bounds: list) -> str | None:
    """`N: usize` -> "usize": the bound of a constant parameter is exactly one integer type."""
    if len(bounds) != 1:
        return None
    name = getattr(bounds[0], "name", bounds[0])
    ty = TYPE_ALIASES.get(name, name)
    return ty if ty in INTS else None


def _in_std(d: Node) -> bool:
    """Is `d` declared in the standard library (`greengold/std`)? Those bodies are checked by the test suite."""
    name = str(getattr(d, "filename", "") or "").replace("\\", "/")
    return "/greengold/std/" in name or "/greengold/core/" in name


# Builtin features: name -> (satisfying types, explanation for those that do not)
BUILTIN_FEATURES: dict[str, tuple[set[str], str]] = {
    "Num": (NUMERIC, "only numeric types are `Num`"),
    "Int": (INTS, "only integer types are `Int`"),
    "Float": (FLOATS, "only f32/f64 are `Float`"),
    "Ord": (NUMERIC | {"str", "string"}, "only numbers and text can be ordered with `<`, `>`"),
    "Eq": (NUMERIC | {"bool", "str", "string"}, "`==` compares numbers, bool, text, and structs, enums, and lists of them"),
    "Copy": (set(), "values of this type are moved, not copied (it owns heap memory, a handle, or has `drop`)"),
    "Key": (INTS | {"bool", "str", "string"},
            "a key is an integer, `bool`, text, a struct, enum, or list of them without floats, or a type with "
            "`fn hash(self: Self) -> u64` and `fn eq(self: Self, other: Self) -> bool`"),
}

# The methods an archetype of `T: Key` has (`hash(x)` and `==` call them).
_KEY_METHODS = """feature __Key:
    fn hash(self: Self) -> u64
    fn eq(self: Self, other: Self) -> bool
"""


def _key_feature() -> FeatureDecl:
    from .diagnostics import DiagnosticBag
    from .lexer import tokenize
    from .parser import parse
    diags = DiagnosticBag()
    return parse(tokenize(_KEY_METHODS, diags), diags).decls[0]

# One type of each kind in a closed builtin bound: a body that works for these works for the whole set.
BOUND_REPRESENTATIVES: dict[str, list[str]] = {
    "Int": ["i8", "u8", "i64", "usize"],
    "Float": ["f16", "f32", "f64"],
    "Num": ["i8", "u8", "i64", "usize", "f32", "f64"],
    "Ord": ["i8", "u8", "i64", "usize", "f32", "f64", "str"],
    "Eq": ["i8", "u8", "i64", "usize", "f32", "f64", "bool", "str"],
}

MAX_INSTANTIATION_DEPTH = 64


def _has_cast(e: Expr) -> bool:
    """A constant expression that names a type (`u64(7)`, `u64(1) << 63`) has that type, so it is not a bare literal."""
    if isinstance(e, Cast):
        return True
    if isinstance(e, Unary):
        return _has_cast(e.operand)
    if isinstance(e, Binary):
        return _has_cast(e.left) or _has_cast(e.right)
    return False


class GenericsMixin:
    # -- template registry ------------------------------------------------------------

    @staticmethod
    def _reserved_names(d: Node) -> set[str]:
        """Names the user cannot define: builtins + (except prelude itself) prelude names."""
        return BUILTINS if getattr(d, "from_prelude", False) else BUILTINS | PRELUDE_NAMES

    def _register_generic_type(self, d: StructDecl | EnumDecl) -> None:
        """Registers `struct Pair[A, B]` / `enum Optional[T]` template (fields resolved at instantiation)."""
        kind = "struct" if isinstance(d, StructDecl) else "enum"
        table = self.generic_structs if kind == "struct" else self.generic_enums
        key = self._sym_key(d, d.name)
        if d.name in PRIMS or d.name in BUILTIN_TYPE_ALIASES or d.name in self._reserved_names(d):
            self._err(d, f"`{d.name}` is a reserved name, cannot be a {kind} name.")
        elif key in table or key in self.generic_structs or key in self.generic_enums \
                or key in self.structs or key in self.enums:
            self._err(d, f"`{d.name}` is already defined.", "Type names must be unique.")
        else:
            table[key] = d

    def _register_generic_fn(self, d: FuncDecl) -> None:
        if d.name == "main":
            self._err(d, "`main` cannot be generic.", "Write as `fn main():`.")
        elif d.name in PRIMS or d.name in BUILTIN_TYPE_ALIASES or d.name in self._reserved_names(d):
            self._err(d, f"`{d.name}` is a reserved name.")
        elif d.name in self.consts:
            self._err(d, f"`{d.name}` is a constant name, cannot be a function name.")
        elif self._type_kind(d.name) or d.name in self.generic_structs or d.name in self.generic_enums:
            self._err(d, f"`{d.name}` is a type name, cannot be a function name.")
        elif self._sym_key(d, d.name) in self.generic_funcs or self._sym_key(d, d.name) in self.funcs:
            self._err(d, f"`{d.name}` is already defined.", "Function names must be unique (no overloading).")
        else:
            key = self._sym_key(d, d.name)
            self.generic_funcs[key] = d
            self.free_funcs.add(key)

    def _register_method_template(self, d: FuncDecl) -> None:
        """`fn Pair[A, B].swap(...)` — method of generic type."""
        owner = d.owner
        assert owner is not None
        tdecl = self.generic_structs.get(owner) or self.generic_enums.get(owner)
        if tdecl is None:
            if owner in self.structs or owner in self.enums:
                self._err(d, f"`{owner}` is not a generic type; cannot write `{owner}[...]`.",
                          f"Write as `impl {owner}:`.")
            else:
                self._err(d, f"No type named `{owner}`; cannot define method.",
                          f"First define `struct {owner}[T]:` (or `enum {owner}[T]:`).")
            return
        if len(d.owner_params) != len(tdecl.type_params):
            if not d.owner_params:
                names = ", ".join(tdecl.type_params)
                self._err(d, f"`{owner}` is a generic type; method must be defined inside `impl {owner}[{names}]:`.")
            else:
                self._err(d, f"`{owner}` takes {len(tdecl.type_params)} type parameter(s), "
                             f"{len(d.owner_params)} written in `impl` definition.")
            return
        key = f"{owner}.{d.name}"  # owner is already the canonical type key
        if key in self.method_templates:
            self._err(d, f"`{key}` is already defined.", "Function names must be unique (no overloading).")
        else:
            self.method_templates[key] = d

    def _check_generic_params(self) -> None:
        """Type parameter names: no duplicates, no collision with existing type/function/constant name."""
        groups: list[tuple[Node, list[str]]] = []
        for decl in list(self.generic_structs.values()) + list(self.generic_enums.values()):
            groups.append((decl, decl.type_params))
        for d in list(self.generic_funcs.values()) + list(self.method_templates.values()):
            groups.append((d, d.type_params or d.owner_params))
        for node, names in groups:
            if getattr(node, "from_prelude", False):
                continue  # prelude type parameters (T, E) can overlap with user names; their scopes are separate
            seen: set[str] = set()
            for n in names:
                if n in seen:
                    self._err(node, f"Type parameter `{n}` is written twice.")
                seen.add(n)
                kind = self._name_kind(n)
                if kind:
                    self._err(node, f"Type parameter `{n}` conflicts with an existing {kind} name.",
                              "Give the type parameter another name, e.g. `T`, `K`, `V`.")

    def _name_kind(self, n: str) -> str | None:
        """Global name kind: 'type' | 'function' | 'constant' | None."""
        if n in self.structs or n in self.enums or n in self.generic_structs or n in self.generic_enums \
                or n in PRIMS or n in PRELUDE_NAMES:
            return "type"
        if n in self.free_funcs or n in self.funcs:
            return "function"
        if n in self.consts:
            return "constant"
        return None

    # -- features (structural; see DESIGN item 20) -----------------------------------

    def _collect_features(self) -> None:
        """Collects `feature` declarations and verifies names in `T: Feature` bounds of generic definitions."""
        self.features = {}
        for d in self.decls:
            if not isinstance(d, FeatureDecl):
                continue
            key = self._sym_key(d, d.name)
            if (d.name in BUILTIN_FEATURES or d.name in PRIMS or d.name in PRELUDE_NAMES or key in self.features
                    or any(isinstance(x, FuncDecl) and x.name == d.name and x.owner is None
                           and self._sym_key(x, x.name) == key for x in self.decls)
                    or any(isinstance(x, (StructDecl, EnumDecl)) and self._sym_key(x, x.name) == key
                           for x in self.decls)):
                self._err(d, f"`{d.name}` is already defined or a reserved name, cannot be a feature name.",
                          "Choose another name.")
                continue
            self.features[key] = d
            seen: set[str] = set()
            for m in d.methods:
                if m.name in seen:
                    self._err(m, f"`{m.name}` declared twice in feature `{d.name}`.")
                seen.add(m.name)
        self._finish_selective(quiet=True)  # `import std.io { Writer }`: a bound may name an imported feature
        known = list(self.features) + list(BUILTIN_FEATURES)
        for d in self.decls:
            if not isinstance(d, (StructDecl, EnumDecl, FuncDecl)):
                continue
            self._enter(d)
            for tp, blist in d.bounds.items():
                if const_param_type(blist) is not None:
                    continue  # `N: usize`: a constant parameter, not a feature bound
                if any(TYPE_ALIASES.get(b.name, b.name) in INTS for b in blist):
                    self._err(blist[0], f"A constant parameter takes one integer type: write `{tp}: usize`.",
                              "A type parameter takes feature bounds (`T: Ord + Eq`); a constant parameter "
                              "(`N: usize`) takes only its type.")
                    continue
                for b in blist:
                    resolved = b.name if b.name in BUILTIN_FEATURES else (self._resolve_simple(b.name) or b.name)
                    if resolved not in self.features and b.name not in BUILTIN_FEATURES:
                        near = difflib.get_close_matches(b.name, known, n=1)
                        hint = f"Did you mean: `{near[0]}`?" if near else \
                            f"Builtin features: {', '.join(BUILTIN_FEATURES)}; define your own feature with `feature Name:`."
                        self._err(b, f"Unknown feature `{b.name}`.", hint)

    def _method_decl(self, owner: str, name: str) -> FuncDecl | None:
        for d in self.decls:
            if isinstance(d, FuncDecl) and d.owner == owner and d.name == name:
                return d
        return None

    @staticmethod
    def _declared_mode(param) -> str:
        """Mode written in the signature.

        An omitted mode on a moved type is later filled in (`read`, then maybe `lend` or
        `consume`). That fill-in is not a different signature: `fn area(self)` still matches
        `fn area(self: Self)`.
        """
        if getattr(param, "mode_inferred", False):
            return ""
        return param.mode or ""

    def _stamp_self(self, tref: TypeRef, self_ty: str) -> None:
        """Bind `Self` in a feature signature to the candidate type (already canonical)."""
        if (tref.name == "Self" and tref.base is None and not tref.args and tref.elem is None
                and not tref.is_fn and not tref.is_ptr and not tref.is_slice and not tref.is_array):
            tref.resolved = self_ty  # type: ignore[attr-defined]
            tref.name = self_ty
            tref.qualifier = None
            return
        if tref.elem is not None:
            self._stamp_self(tref.elem, self_ty)
        for arg in tref.args:
            self._stamp_self(arg, self_ty)
        for p in tref.fn_params:
            self._stamp_self(p, self_ty)
        if tref.fn_ret is not None:
            self._stamp_self(tref.fn_ret, self_ty)

    def _signature_type(self, tref: TypeRef | None, scope: Node, self_ty: str | None,
                        already: str | None = None) -> str:
        """Canonical type of one signature position. `self_ty` binds `Self` in a feature signature."""
        if already:
            return already
        if tref is None:
            return "void"
        node = tref
        if self_ty is not None:
            node = copy.deepcopy(tref)
            self._stamp_self(node, self_ty)
        saved = self.scope_slug
        self._enter(scope)
        try:
            return self._resolve(node)
        finally:
            self.scope_slug = saved

    def _is_archetype(self, ty: str) -> bool:
        return bool(getattr(self.structs.get(ty), "archetype", False))

    def _feature_problems(self, ty: str, feature: str) -> list[str]:
        """Returns reasons if type `ty` does not satisfy `feature` (empty list: satisfies)."""
        if feature == "Copy":
            info = self.structs.get(ty)
            copyable = not self._moves(ty) or (info is not None and getattr(info, "archetype_copy", False))
            return [] if copyable else [BUILTIN_FEATURES["Copy"][1]]
        if feature == "Key":
            if ty in BUILTIN_FEATURES["Key"][0] or int_base(ty) in INTS:
                return []
            base = (generic_parts(ty) or (ty, []))[0]
            has = all(f"{ty}.{m}" in self.funcs or f"{base}.{m}" in self.method_templates for m in ("hash", "eq"))
            if has or (not self._is_archetype(ty) and self._eq_problem(ty, None, hashing=True) is None):
                return []  # field by field
            return [BUILTIN_FEATURES["Key"][1]]
        if feature == "Eq" and ty not in BUILTIN_FEATURES["Eq"][0] and not self._is_archetype(ty):
            return [] if self._eq_problem(ty, None) is None else [BUILTIN_FEATURES["Eq"][1]]
        if feature in BUILTIN_FEATURES:
            return [] if ty in BUILTIN_FEATURES[feature][0] else [BUILTIN_FEATURES[feature][1]]
        t = self.features.get(feature)
        if t is None:
            return []
        parts = generic_parts(ty)
        base = parts[0] if parts else ty
        generic_owner = parts is not None or base in self.generic_structs or base in self.generic_enums
        if base in PRIMS and feature not in BUILTIN_FEATURES:
            return [f"Primitive `{ty}` cannot implement user feature `{feature}`."]
        out: list[str] = []
        for m in t.methods:
            d = self._method_decl(base, m.name)
            if d is not None and self.cur is not None and not self._is_visible(d):
                out.append(f"`{m.name}` is private")
                continue
            if d is None:
                if not m.body:
                    out.append(f"`fn {base}.{m.name}(...)` is not defined")
                continue
            if len(d.params) != len(m.params):
                out.append(f"`{m.name}` must take {len(m.params)} parameter(s), takes {len(d.params)}")
                continue
            for a, b in zip(d.params, m.params):
                if self._declared_mode(a) != self._declared_mode(b):
                    out.append(f"in method `{m.name}`, parameter `{a.name}` mode must be `{b.mode}`")
                    continue
                if generic_owner:
                    continue
                want = self._signature_type(b.type_ref, t, ty)
                got = self._signature_type(a.type_ref, d, None, getattr(a, "ty", None))
                if want != got and want != ERR and got != ERR:
                    out.append(f"in method `{m.name}`, parameter `{a.name}` must be `{want}`")
            if not generic_owner:
                want = self._signature_type(m.ret, t, ty)
                got = self._signature_type(d.ret, d, None, getattr(d, "ret_ty", None))
                if want != got and want != ERR and got != ERR:
                    out.append(f"method `{m.name}` must return `{want}`, returns `{got}`")
        return out

    def _check_bounds(self, bounds: dict, bindings: dict[str, str], node: Node, what: str) -> bool:
        ok = True
        for tp, ty in bindings.items():
            cty = const_param_type(bounds.get(tp, []))
            if ty == ERR or (cty is None) == (not is_const_arg(ty)):
                continue
            if cty is None:
                self._err(node, f"`{tp}` is a type parameter of {what}, but `{ty}` is a number.",
                          f"Write a type for `{tp}`.", rule="generic-args")
            else:
                self._err(node, f"`{tp}` is a constant (`{tp}: {cty}`) of {what}, but `{ty}` is a type.",
                          f"Write a number for `{tp}`, such as `[3]`.", rule="generic-args")
            ok = False
        for tp, (cty, ty) in ((tp, (const_param_type(bounds.get(tp, [])), bindings.get(tp))) for tp in bounds):
            if cty is not None and ty is not None and is_const_arg(ty):
                lo, hi = INT_RANGES[cty]
                if not lo <= int(ty) <= hi:
                    self._err(node, f"`{tp} = {ty}` does not fit in `{cty}`.", rule="out-of-range")
                    ok = False
        if not ok:
            return False
        for tp, blist in bounds.items():
            ty = bindings.get(tp)
            if ty is None or ty == ERR or const_param_type(blist) is not None:
                continue
            for b in blist:
                feature = b.name if b.name in BUILTIN_FEATURES else (self._resolve_simple(b.name) or b.name)
                probs = self._feature_problems(ty, feature)
                if probs:
                    self._err(node, f"Type `{ty}` does not satisfy `{b.name}` bound ({what}, `{tp}: {b.name}`): "
                                    + "; ".join(probs) + ".",
                              f"Provide a type satisfying `{b.name}` for `{tp}`."
                              if b.name in BUILTIN_FEATURES else f"Define all methods of feature `{b.name}` for `{ty}`.")
                    ok = False
        return ok

    # -- checking a generic body against its bounds ------------------------------------

    def _check_against_bounds(self) -> None:
        """Checks each generic body of this program (not the prelude or `std`) against its bounds."""
        templates = [d for d in list(self.generic_funcs.values()) + list(self.method_templates.values())
                     if not getattr(d, "from_prelude", False) and not _in_std(d)
                     and not getattr(d, "from_feature_default", False)
                     and not getattr(d, "is_lambda", False)]  # checked inside the enclosing function's body
        for d in templates:
            self._check_template(d)

    def _template_bounds(self, d: FuncDecl) -> tuple[list[str], dict[str, list[str]], str | None]:
        """Type parameters (owner's first), their bound names, and the generic owner type."""
        owner_decl = self.generic_structs.get(d.owner) or self.generic_enums.get(d.owner) if d.owner else None
        params = list(d.owner_params) + list(d.type_params)
        bounds: dict[str, list[str]] = {}
        if owner_decl is not None:  # `impl Pair[A, B]` uses the names of the impl, bounds of the type
            for mine, theirs in zip(d.owner_params, owner_decl.type_params):
                bounds[mine] = [b.name for b in owner_decl.bounds.get(theirs, [])]
        for tp, blist in d.bounds.items():
            bounds.setdefault(tp, []).extend(b.name for b in blist)
        return params, bounds, (d.owner if owner_decl is not None else None)

    def _check_template(self, d: FuncDecl) -> None:
        params, bounds, owner = self._template_bounds(d)
        rounds: list[dict[str, str]] = []
        reps: dict[str, list[str]] = {}
        for tp in params:
            names = bounds.get(tp, [])
            if len(names) == 1 and TYPE_ALIASES.get(names[0], names[0]) in INTS:
                reps[tp] = [CONST_REPRESENTATIVE]  # `N: usize` is checked with one large value
                continue
            closed = [n for n in names if n in BOUND_REPRESENTATIVES]
            if closed:
                allowed = set.intersection(*(BUILTIN_FEATURES[n][0] for n in closed))
                reps[tp] = [t for t in BOUND_REPRESENTATIVES[closed[0]] if t in allowed] or [sorted(allowed)[0]]
        width = max([len(v) for v in reps.values()] + [1])
        for i in range(width):  # one round per representative ("diagonal"), not every combination
            rounds.append({tp: reps[tp][i % len(reps[tp])] for tp in reps})
        before = (set(self.funcs), set(self.structs), set(self.enums), len(self.instances), len(self.decls),
                  len(self.type_order), len(self.instance_cnames))
        saved_pending = self.pending
        self.pending = []
        found: list = []
        try:
            for binding in rounds:
                for tp in params:
                    if tp not in binding:
                        binding[tp] = self._archetype(tp, bounds.get(tp, []), d)
                found.extend(self._check_template_round(d, params, binding, owner))
        finally:
            self._forget_since(before)
            self.pending = saved_pending
        self._report_template_errors(found)

    def _archetype(self, tp: str, bounds: list[str], site: FuncDecl) -> str:
        """A stand-in for `tp`: the methods of its feature bounds, moved unless `Copy` is a bound."""
        if tp in self.structs and getattr(self.structs[tp], "archetype", False):
            return tp
        sdecl = StructDecl(tp, [])
        sdecl.line, sdecl.col, sdecl.length = site.line, site.col, site.length
        sdecl.filename = getattr(site, "filename", None)
        sdecl.module_slug = getattr(site, "module_slug", "")
        sdecl.is_pub = True
        info = StructInfo(tp, {}, sdecl)
        info.archetype = True  # type: ignore[attr-defined]
        info.archetype_copy = "Copy" in bounds  # type: ignore[attr-defined]
        self.structs[tp] = info
        self.type_order.append(tp)
        saved_scope = self.scope_slug
        self.scope_slug = getattr(site, "module_slug", "") or ""   # names in a bound mean what they mean where the generic is written
        for b in bounds:
            slug = getattr(site, "module_slug", "")
            own = f"{slug}::{b}"  # a feature of the module that declares the generic, wherever it is checked from
            key = b if b in BUILTIN_FEATURES else (own if slug and own in self.features else (self._resolve_simple(b) or b))
            feature = _key_feature() if b == "Key" else self.features.get(key)
            if feature is None:
                continue
            for m in feature.methods:
                if f"{tp}.{m.name}" in self.funcs:
                    continue
                stub = copy.deepcopy(m)
                stub.owner = tp
                stub.body = []
                stub.archetype_stub = True  # type: ignore[attr-defined]
                stub.is_pub = True  # type: ignore[attr-defined]
                stub.module_slug = getattr(feature, "module_slug", "")  # its types resolve where the feature is written
                from .ast_nodes import subst_self_func
                subst_self_func(stub, tp, [])
                self.decls.append(stub)
                self._declare_function(stub, f"{tp}.{m.name}")
        self.scope_slug = saved_scope
        return tp

    def _check_template_round(self, d: FuncDecl, params: list[str], binding: dict[str, str],
                              owner: str | None) -> list:
        """Instantiates `d` with `binding` and checks the copy; returns the diagnostics it caused."""
        mark = len(self.diags.items)
        shown = ", ".join(f"{tp} = {binding[tp]}" for tp in params)
        note = Note(d.line, d.col, max(d.length, 1),
                    f"checked where it is declared, with {shown}: a body may use only what its bounds promise")
        if owner is not None:
            ot = self._instantiate_type(owner, [binding[tp] for tp in d.owner_params], d)
            if ot == ERR:
                return self._take_diags(mark)
            sub = {tp: binding[tp] for tp in d.type_params}
            info = self.funcs.get(f"{ot}.{d.name}") if not sub else None
            if info is None:
                tmpl = d
                if sub:
                    key = make_generic(f"{ot}.{d.name}", [sub[tp] for tp in d.type_params])
                    info = self._instantiate_func(tmpl, key, {**dict(zip(d.owner_params, [binding[t] for t in d.owner_params])), **sub}, ot, d)
                else:
                    info = self._method_template_info(ot, d.name, d)
        else:
            base = self._sym_key(d, d.name)
            key = make_generic(base, [binding[tp] for tp in d.type_params])
            info = self.funcs.get(key) or self._instantiate_func(d, key, dict(binding), None, d)
        if info is None:
            return self._take_diags(mark)
        inst = info.decl
        inst.inst_note = note  # type: ignore[union-attr]
        while self.pending:
            self._check_function(self.pending.pop(0))
        if len(self.diags.items) == mark and isinstance(inst, FuncDecl) and not inst.type_params:
            from .typecheck import MoveAnalyzer
            ma = MoveAnalyzer(self.program, self.diags)
            ma.run_on([inst])
        return self._take_diags(mark)

    def _take_diags(self, mark: int) -> list:
        found = self.diags.items[mark:]
        del self.diags.items[mark:]
        return found

    def _forget_since(self, before: tuple) -> None:
        """Drops what the bound check created: archetypes and the instances that use them."""
        funcs, structs, enums, n_inst, n_decls, n_order, n_cnames = before
        for k in [k for k in self.funcs if k not in funcs]:
            del self.funcs[k]
        for k in [k for k in self.structs if k not in structs]:
            del self.structs[k]
        for k in [k for k in self.enums if k not in enums]:
            del self.enums[k]
        del self.instances[n_inst:]
        del self.decls[n_decls:]
        del self.type_order[n_order:]
        del self.instance_cnames[n_cnames:]

    def _report_template_errors(self, found: list) -> None:
        """Keeps one copy of each error, and none where a real instance already reported that line."""
        taken = {(getattr(x, "filename", None), x.line) for x in self.diags.items}
        for diag in found:  # the first round that fails a line explains it; later rounds repeat it
            key = (getattr(diag, "filename", None), diag.line)
            if key in taken:
                continue
            taken.add(key)
            self.diags.items.append(diag)

    # -- type application: Pair[i32, f64] ----------------------------------------------

    def _check_type_arg(self, ty: str, node: Node) -> bool:
        """Slice is invalid as a type argument (`consume`/`read`/`lend` are already absent in syntax)."""
        if ty != ERR and is_slice_type(ty):
            self._err(node, "Slice (`[]T`) cannot be a type argument; slices can only be function parameters.",
                      "Use array type `[N]T` instead of slice.")
            return False
        return ty != ERR

    def _resolve_app(self, base: str, trefs: list[TypeRef], node: Node) -> str:
        """Resolves and instantiates generic type application `base[trefs...]`; returns canonical name."""
        base = TYPE_ALIASES.get(base, base)
        if base in HEAP_BUILTINS:
            return self._resolve_heap_type(base, trefs, node)
        decl = self.generic_structs.get(base) or self.generic_enums.get(base)
        if decl is None:
            if base in PRIMS or base in self.structs or base in self.enums:
                self._err(node, f"`{base}` is not a generic type, cannot take type arguments.",
                          f"Write only `{base}`.")
            else:
                self._err(node, f"Unknown type `{base}`.")
            return ERR
        for t in trefs:
            t.const_ok = True  # type: ignore[attr-defined]  # `Grid[2, 3]` / `Grid[W, H]`
        args = [self._resolve(t) for t in trefs]
        if len(args) != len(decl.type_params):
            self._err(node, f"`{base}` expects {len(decl.type_params)} type argument(s), found {len(args)}.",
                      f"Write as `{make_generic(base, decl.type_params)}` (no partial type arguments).")
            return ERR
        ok = True
        for t, ty in zip(trefs, args):
            ok = self._check_type_arg(ty, t) and ok
        if not ok:
            return ERR
        return self._instantiate_type(base, args, node)

    def _resolve_heap_type(self, base: str, trefs: list[TypeRef], node: Node) -> str:
        """`Box[T]` / `List[T]`: compiler-builtin heap-owning types."""
        if len(trefs) != 1:
            self._err(node, f"`{base}` expects 1 type argument(s), found {len(trefs)}.", f"Write as `{base}[T]`.")
            return ERR
        ty = self._resolve(trefs[0])
        if not self._check_type_arg(ty, trefs[0]):
            return ERR
        return make_generic(base, [ty])

    def _instantiate_type(self, base: str, args: list[str], node: Node) -> str:
        """Creates `Pair[i32, f64]` instance for `Pair` + [i32, f64] (if not already created)."""
        canon = make_generic(base, args)
        if canon in self.structs or canon in self.enums:
            return canon  # cache: instantiation with identical type arguments is performed once
        decl = self.generic_structs.get(base) or self.generic_enums[base]
        if not self._check_bounds(decl.bounds, dict(zip(decl.type_params, args)), node, canon):
            return ERR
        if not self._enter_instantiation(node):
            return ERR
        saved, saved_scope = self.tparams, self.scope_slug
        self.tparams = dict(zip(decl.type_params, args))
        self._enter(decl)  # field types are names of the module that declares the type
        try:
            self.type_order.append(canon)
            if isinstance(decl, StructDecl):
                sinfo = StructInfo(canon, {}, decl)
                self.structs[canon] = sinfo  # record first: self-referential types get caught by cycle detection
                self._fill_struct(sinfo)
            else:
                einfo = EnumInfo(canon, {}, decl)
                self.enums[canon] = einfo
                self._fill_enum(einfo)
        finally:
            self.tparams, self.scope_slug = saved, saved_scope
            self.depth -= 1
        self.instance_cnames.append((mangle(canon), canon, node))
        return canon

    def _enter_instantiation(self, node: Node) -> bool:
        """Counts instantiation depth; errors and returns False if exceeding 64 (caller does not do depth -= 1)."""
        if self.depth >= MAX_INSTANTIATION_DEPTH:
            self._err(node, "possible infinite recursive instantiation (instantiation depth exceeded 64).",
                      "A generic definition may be instantiating itself with larger type parameters; break the cycle.")
            return False
        self.depth += 1
        return True

    def _mentions_tparam(self, tref: TypeRef) -> bool:
        """Does the type expression contain an active type parameter (T)?"""
        if tref.elem is not None and self._mentions_tparam(tref.elem):
            return True
        return tref.name in self.tparams or any(self._mentions_tparam(a) for a in tref.args)

    # -- generic enum variant constructor: where do type arguments come from? ----------------------

    def _generic_enum_type(self, base: str, targs: list[TypeRef] | None, vname: str,
                           args: list[Expr] | None, expected: str | None, node: Node) -> str:
        """Finds canonical name of enum instance for `Optional[i32].None`, `Valid(5)`, `None` ...

        Priority: (1) explicit type arguments, (2) expected type (variable type, parameter, return type),
        (3) inference from payload arguments. If none suffice, an error is reported.
        """
        decl = self.generic_enums[base]
        if targs is not None:
            return self._resolve_app(base, targs, node)
        parts = generic_parts(expected) if expected else None
        if parts is not None and parts[0] == base:
            return expected  # type: ignore[return-value]
        variant = next((v for v in decl.variants if v.name == vname), None)
        if variant is None:
            self._err(node, f"`{base}` enum has no variant named `{vname}`.",
                      f"`{base}` variants: {', '.join(v.name for v in decl.variants)}.")
            return ERR
        bindings: dict[str, str] = {}
        if args is not None and len(args) == len(variant.payload):
            deferred: list[tuple[str, Expr]] = []
            for tref, a in zip(variant.payload, args):
                target = a
                if not any(self._pattern_mentions(tref, t) for t in decl.type_params):
                    continue
                if is_const_expr(target) and tref.name in decl.type_params:
                    deferred.append((tref.name, target))
                    continue
                ty = self._expr(target)
                if ty == ERR or not self._unify(tref, ty, bindings, decl.type_params, target):
                    return ERR
            for name, target in deferred:
                bindings.setdefault(name, "f64" if self._is_float_const(target) else "i32")
        missing = [t for t in decl.type_params if t not in bindings]
        if missing:
            shown = ", ".join(bindings.get(t, "i32") for t in decl.type_params)
            self._err(node, f"type could not be inferred, write `{base}[{shown}].{vname}` or specify type.",
                      f"Cannot determine `{', '.join(missing)}`; specify type explicitly, e.g. `x: {base}[{shown}] = ...`.")
            return ERR
        tys = [bindings[t] for t in decl.type_params]
        if not all(self._check_type_arg(ty, node) for ty in tys):
            return ERR
        return self._instantiate_type(base, tys, node)

    # -- function / method instantiation ------------------------------------------------------

    def _instantiate_func(self, tmpl: FuncDecl, key: str, bindings: dict[str, str],
                          owner_ty: str | None, call: Node) -> FuncInfo | None:
        """Copies template body, produces a function instance with `bindings`, and queues it."""
        existing = self.funcs.get(key)
        if existing is not None:
            return existing
        if not self._check_bounds(self._all_bounds(tmpl), bindings, call, key):
            return None
        if not self._enter_instantiation(call):
            return None
        d = copy.deepcopy(tmpl)
        d.type_params, d.owner_params = [], []  # copy is no longer a template
        d.owner = owner_ty
        d.inst_key = key
        shown = ", ".join(f"{k} = {v}" for k, v in bindings.items())
        d.inst_note = Note(call.line, call.col, call.length,
                           f"instantiated with {shown}, call: {self.filename}:{call.line}:{call.col}")
        saved = self.tparams
        self.tparams = bindings
        try:
            info = self._declare_function(d, key, instance=True)
        finally:
            self.tparams = saved
            self.depth -= 1
        if info is None:
            return None
        info.bindings = bindings
        info.const_types = self._const_types(tmpl)  # type: ignore[attr-defined]
        info.is_instance = True
        info.depth = self.depth + 1
        self.instances.append(d)
        self.pending.append(info)
        self.instance_cnames.append((func_cname(key), key, call))
        return info

    def _all_bounds(self, tmpl: FuncDecl) -> dict:
        """Bounds of a template's parameters: a method of `impl Grid[W, H]` gets the bounds of `Grid`'s."""
        out = dict(tmpl.bounds)
        owner_decl = (self.generic_structs.get(tmpl.owner) or self.generic_enums.get(tmpl.owner)) if tmpl.owner else None
        if owner_decl is not None:
            for mine, theirs in zip(tmpl.owner_params, owner_decl.type_params):
                if theirs in owner_decl.bounds:
                    out.setdefault(mine, owner_decl.bounds[theirs])
        return out

    def _const_types(self, tmpl: FuncDecl) -> dict[str, str]:
        """Constant parameters of a template (its own and its generic owner's) -> their integer types."""
        out: dict[str, str] = {}
        owner_decl = (self.generic_structs.get(tmpl.owner) or self.generic_enums.get(tmpl.owner)) if tmpl.owner else None
        if owner_decl is not None:
            for mine, theirs in zip(tmpl.owner_params, owner_decl.type_params):
                cty = const_param_type(owner_decl.bounds.get(theirs, []))
                if cty is not None:
                    out[mine] = cty
        for tp, blist in tmpl.bounds.items():
            cty = const_param_type(blist)
            if cty is not None:
                out[tp] = cty
        return out

    def _method_template_info(self, ot: str, method: str, call: Node) -> FuncInfo | None:
        """`p.swap()`: if receiver type is generic instance (Pair[i32, f64]), generates method for that instance."""
        parts = generic_parts(ot)
        if parts is None:
            return None
        base, args = parts
        tmpl = self.method_templates.get(f"{base}.{method}")
        if tmpl is None:
            return None
        bindings = dict(zip(tmpl.owner_params, args))
        return self._instantiate_func(tmpl, f"{ot}.{method}", bindings, ot, call)

    # -- generic function call ------------------------------------------------------------

    def _generic_call(self, e: Call) -> str:
        """`max(3, 9)` or `max[i64](5, 2)`."""
        d = self.generic_funcs[getattr(e, "func_key", None) or e.callee]
        args = [a for a in e.args]
        if len(e.args) != len(d.params):
            sig = ", ".join(f"{p.name}: {p.type_ref.name}" for p in d.params)
            self._err(e, f"`{e.callee}` expects {len(d.params)} argument(s), found {len(e.args)}.",
                      f"Signature: {e.callee}[{', '.join(d.type_params)}]({sig})")
            for a in args:
                self._expr_any(a)
            return ERR
        if e.type_args:
            if len(e.type_args) != len(d.type_params):
                self._err(e, f"`{e.callee}` expects {len(d.type_params)} type argument(s), found {len(e.type_args)} "
                             "(partial type arguments not allowed).",
                          f"Provide all: `{e.callee}[{', '.join(d.type_params)}](...)`, or none at all (inference).")
                for a in args:
                    self._expr_any(a)
                return ERR
            for t in e.type_args:
                t.const_ok = True  # type: ignore[attr-defined]  # `total[3](xs)`
            tys = [self._resolve(t) for t in e.type_args]
            if not all(self._check_type_arg(ty, t) for ty, t in zip(tys, e.type_args)):
                for a in args:
                    self._expr_any(a)
                return ERR
            bindings = dict(zip(d.type_params, tys))
        else:
            inferred = self._infer_bindings(d, e, args)
            if inferred is None:
                return ERR
            bindings = inferred
        base_name = getattr(e, "func_key", None) or e.callee
        key = make_generic(base_name, [bindings[t] for t in d.type_params])
        info = self._instantiate_func(d, key, bindings, None, e)
        if info is None:
            for a in args:
                self._expr_any(a)
            return ERR
        info = self._specialize_for_closures(info, e.args, e)
        key = info.key
        e.inst_key = key
        self._check_args(e, e.callee, info.params, e.args, None)
        return info.ret

    def _infer_bindings(self, d: FuncDecl, e: Call, args: list[Expr]) -> dict[str, str] | None:
        """Unifies parameter types with argument types (unification).

        Inspects non-constant arguments first, then number constants. For T that is still unresolved,
        constant default is applied (integer -> i32, float -> f64). No inference from return type.
        """
        tparams = d.type_params
        bindings: dict[str, str] = {}
        deferred: list[tuple[str, Expr]] = []
        failed = False
        for param, target in zip(d.params, args):
            pattern = param.type_ref
            if not any(self._pattern_mentions(pattern, t) for t in tparams):
                continue
            if is_const_expr(target) and pattern.name in tparams and not _has_cast(target):
                deferred.append((pattern.name, target))
                continue
            if isinstance(target, SliceExpr):
                target.in_call_arg = True
            if pattern.is_fn and pattern.fn_boxed:  # a lambda here becomes an owned `Fn`: it owns its captures
                target.owns_captures = True  # type: ignore[attr-defined]
            ty = self._expr(target)
            if ty == ERR:
                failed = True
            elif not self._unify(pattern, ty, bindings, tparams, target):
                failed = True
        for name, target in deferred:
            if name not in bindings:
                bindings[name] = "f64" if self._is_float_const(target) else "i32"
        if failed:
            return None
        for t in tparams:
            if t not in bindings:
                self._err(e, f"type could not be inferred: `{t}` cannot be determined from arguments.",
                          f"Specify type argument explicitly: `{e.callee}[{', '.join(tparams)}](...)`.")
                return None
            if is_slice_type(bindings[t]):
                self._err(e, "Slice (`[]T`) cannot be a type argument; slices can only be function parameters.",
                          "Pass array `[N]T` instead of slice.")
                return None
        return bindings

    def _pattern_mentions(self, pattern: TypeRef, tparam: str) -> bool:
        if pattern.elem is not None and self._pattern_mentions(pattern.elem, tparam):
            return True
        if pattern.is_array and isinstance(pattern.size_expr, Name) and pattern.size_expr.name == tparam:
            return True
        if pattern.is_fn and (any(self._pattern_mentions(p, tparam) for p in pattern.fn_params)
                              or pattern.fn_ret is not None and self._pattern_mentions(pattern.fn_ret, tparam)):
            return True
        return pattern.name == tparam or any(self._pattern_mentions(a, tparam) for a in pattern.args)

    def _unify(self, pattern: TypeRef, actual: str, bindings: dict[str, str], tparams: list[str],
               node: Node) -> bool:
        """Unifies `pattern` (T, []T, Pair[T, U] ...) with actual type; errors on contradiction."""
        if pattern.is_slice or pattern.is_array:
            assert pattern.elem is not None
            if is_slice_type(actual):
                return self._unify(pattern.elem, slice_elem_type(actual), bindings, tparams, node)
            if is_array_type(actual):
                size = pattern.size_expr
                if pattern.is_array and isinstance(size, Name) and size.name in tparams:  # `[N]T` gives `N`
                    n = str(array_info(actual)[0])
                    prev = bindings.get(size.name)
                    if prev is not None and prev != n:
                        self._err(node, f"{size.name} was inferred as both {prev} and {n}.",
                                  "The arrays must have the same length.")
                        return False
                    bindings[size.name] = n
                return self._unify(pattern.elem, array_info(actual)[1], bindings, tparams, node)
            return True  # mismatch is caught as 'Type mismatch' by argument checking
        if pattern.is_fn:  # `f: fn(T) -> U` given a function value or a closure
            sig = self._closure_signature(actual) if actual in self.closures else actual
            if not is_fn_type(sig) and not is_boxed_fn(sig):
                return True
            ps, ret = fn_parts(sig)
            if len(ps) != len(pattern.fn_params):
                return True
            ok = all(self._unify(p, a, bindings, tparams, node) for p, a in zip(pattern.fn_params, ps))
            if pattern.fn_ret is not None:
                ok = self._unify(pattern.fn_ret, ret, bindings, tparams, node) and ok
            return ok
        if pattern.args:
            parts = generic_parts(actual)
            # `Task[T]` written in module `tasks` names `tasks::Task`; a wrong match is still caught by the argument check
            same_base = parts is not None and (parts[0] == pattern.base or parts[0].rsplit("::", 1)[-1] == pattern.base)
            if parts is not None and same_base and len(parts[1]) == len(pattern.args):
                return all(self._unify(p, a, bindings, tparams, node) for p, a in zip(pattern.args, parts[1]))
            return True
        if pattern.name in tparams:
            prev = bindings.get(pattern.name)
            if prev is not None and prev != actual:
                self._err(node, f"{pattern.name} was inferred as both {prev} and {actual}.",
                          f"Argument types must be identical; or specify type argument explicitly: `f[{prev}](...)`.")
                return False
            bindings[pattern.name] = actual
        return True

    def _is_float_const(self, e: Expr) -> bool:
        if isinstance(e, FloatLit):
            return True
        if isinstance(e, IntLit):
            return False
        if isinstance(e, Unary):
            return self._is_float_const(e.operand)
        if isinstance(e, Binary):
            return self._is_float_const(e.left) or self._is_float_const(e.right)
        if isinstance(e, Cast):
            return e.target_type in ("f16", "f32", "f64")
        return False

    # -- T(x): numeric conversion with type parameter ------------------------------------------------

    def _tparam_cast(self, e: Call) -> str:
        """`T(x)` in body: if T is instantiated with numeric type, behaves as `i32(x)` conversion."""
        target = self.tparams[e.callee]
        args = [a for a in e.args]
        if len(e.args) != 1:
            self._err(e, f"`{e.callee}(...)` conversion takes exactly 1 argument.")
            for a in args:
                self._expr_any(a)
            return ERR
        if target not in NUMERIC:
            self._err(e, f"`{e.callee}(x)` conversion cannot be performed: `{e.callee}` = `{target}` is not a numeric type.",
                      "Numeric conversion can only be used in generics instantiated with numeric types.")
            self._expr_any(args[0])
            return ERR
        cast = Cast(target, args[0], line=e.line, col=e.col, length=e.length)
        ty = self._cast(cast)
        if ty != ERR:
            e.cast_to = target
        return ty
