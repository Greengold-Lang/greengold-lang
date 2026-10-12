"""Closures: lambdas that use variables of the function they are written in.

A lambda is lifted to a hidden top-level function by the parser. When its body names a variable of the
enclosing function, the lambda becomes a closure:

  * A hidden struct `__closure_<lambda>` holds the captured variables. A copyable value is copied in;
    a heap-owning value is held as a `read` reference tied to the struct (the borrow checker then keeps
    that variable alive and unchanged while the closure is used, as for any struct with reference fields).
    When the body changes a captured variable, it is held as a `lend` reference instead (found by a first
    check pass, like inferred parameter modes; see check_program).
  * The lifted function gets a first parameter `__env: read __closure_<lambda>`; captured names in its
    body become `__env.name`.
  * The lambda expression becomes a struct literal of that type, and `f(x)` on a closure value calls
    the lifted function with the closure as `__env`.
  * Passing a closure to a parameter of function type (`fn(i32) -> i32`) compiles a copy of the callee
    for that closure (monomorphization), so the call is direct and has no runtime cost.
  * `Fn(A) -> R` is an owned closure value that can be returned, stored, and put in lists. A lambda
    written where a `Fn` is expected owns its captures (heap values are moved in, the rest copied); the
    environment lives on the heap with a reference count (`clone` shares it). A plain function converts
    to `Fn` too.

  * A lambda written inside a generic function (or a method of a generic type) is itself generic over
    the same type parameters (the parser gives it them); each instance of the function reaches its own
    instance of the lambda (`_generic_lambda`), so `fn(x: T) => x > limit` works for every `T`.
"""
from __future__ import annotations

import copy
from dataclasses import fields as dc_fields

from .ast_nodes import (
    walk,
    Call, FieldAccess, FieldDecl, FieldInit, FuncDecl, MethodCall, Name, Node, Param, StructDecl, StructLit, TypeRef,
)
from .typeinfo import (
    ERR, FuncInfo, ParamInfo, StructInfo, VarInfo, fn_parts, is_boxed_fn, is_fn_type, is_slice_type, make_fn, make_generic,
)

CLOSURE_PREFIX = "__closure_"
ENV = "__env"


def _walk(node):
    return walk(node)


def _used_names(decl: FuncDecl) -> list[str]:
    """Variable names a lambda body refers to, in first-use order (calls through a name included)."""
    params = {p.name for p in decl.params}
    out: list[str] = []
    for n in _walk(decl.body):
        name = None
        if isinstance(n, Name):
            name = n.name
        elif isinstance(n, Call) and not n.qualifier:
            name = n.callee
        if name is not None and name not in params and name not in out:
            out.append(name)
    return out


def _replace(node: Node, new: Node) -> None:
    """Turns `node` into `new` in place, so parents keep pointing at it."""
    keep = {k: getattr(node, k) for k in ("line", "col", "length", "filename")}
    node.__class__ = new.__class__
    node.__dict__.clear()
    node.__dict__.update(new.__dict__)
    for k, v in keep.items():
        setattr(node, k, v)


def _at(new: Node, site: Node) -> Node:
    new.line, new.col, new.length = site.line, site.col, site.length
    new.filename = getattr(site, "filename", None)
    return new


class ClosureMixin:
    """TypeChecker part for capturing lambdas. Expects TypeChecker attributes (structs, funcs, ...)."""

    # -- lambda bodies are checked when the lambda is reached, so captures are known first --------
    def _init_closures(self, capture_modes: dict[tuple[str, str], str] | None = None) -> None:
        # (lambda key, captured name) -> "lend" when the body changes it (found by an earlier check pass)
        self.capture_modes: dict[tuple[str, str], str] = dict(capture_modes or {})
        self.closures: dict[str, str] = {}       # closure struct name -> lambda function key
        self.lambda_queued: set[str] = set()     # lambda keys whose bodies are queued for checking
        self.lambda_caps: dict[str, list[tuple[str, str]]] = {}  # lambda key -> [(name, type)]
        self.owning_closures: set[str] = set()   # closures written where a `Fn` is expected: own their captures

    @staticmethod
    def _is_lambda(info: FuncInfo | None) -> bool:
        return info is not None and getattr(info.decl, "is_lambda", False)

    def _generic_lambda(self, name: str, site: Node) -> FuncInfo | None:
        """A lambda written inside a generic function: its instance for the type arguments now bound.
        Its body is checked when the lambda is reached (`_lambda_value`), like any lambda."""
        key = self._resolve_simple(name) or name
        tmpl = self.generic_funcs.get(key)
        if tmpl is None or not getattr(tmpl, "is_lambda", False):
            return None
        if any(t not in self.tparams for t in tmpl.type_params):
            return None
        bindings = {t: self.tparams[t] for t in tmpl.type_params}
        info = self._instantiate_func(tmpl, make_generic(key, [bindings[t] for t in tmpl.type_params]),
                                      bindings, None, site)
        if info is not None and info in self.pending and info.key not in self.lambda_queued:
            self.pending.remove(info)  # checked when reached, once its captures are known
        return info

    def _queue_lambda(self, info: FuncInfo) -> None:
        if info.key not in self.lambda_queued:
            self.lambda_queued.add(info.key)
            self.pending.append(info)

    def _queue_unreached_lambdas(self) -> None:
        for info in list(self.funcs.values()):
            if self._is_lambda(info) and not info.is_instance:
                self._queue_lambda(info)

    # -- the lambda expression ----------------------------------------------------------------
    def _captures(self, info: FuncInfo) -> list[tuple[str, VarInfo]]:
        caps = []
        for name in _used_names(info.decl):  # type: ignore[arg-type]
            var = self._lookup(name)
            if var is not None and var.kind != "const":
                caps.append((name, var))
        return caps

    def _lambda_value(self, e: Name, info: FuncInfo, expected: str | None) -> str:
        """`fn(x: i32) -> i32 => x + k` as a value: a function pointer, or a closure when it captures."""
        if info.key in self.lambda_caps:  # already a closure (reached again, e.g. in another instance)
            closure = self._closure_of(info.key)
            known = self.lambda_caps[info.key]
            now = [(n, self._lookup(n)) for n, _ in known]
            if any(v is None or v.ty != t for (_, t), (_, v) in zip(known, now)):
                self._err(e, "This lambda captures variables with different types in another instance.",
                          "Move the lambda out of the generic function, or pass the values as parameters.")
                return ERR
            caps = now
        else:
            caps = self._captures(info)
            if not caps:
                self._queue_lambda(info)
                return self._func_ref(e, info)
            own = (expected is not None and is_boxed_fn(expected)) or getattr(e, "owns_captures", False)
            closure = self._make_closure(info, caps, e, own=own)
            if closure is None:
                return ERR
        self._queue_lambda(info)
        lit = _at(StructLit(closure, [_at(FieldInit(n, _at(Name(n), e)), e) for n, _ in caps]), e)
        _replace(e, lit)
        return self._struct_lit(e)  # type: ignore[arg-type]

    def _closure_of(self, lambda_key: str) -> str:
        return next(c for c, k in self.closures.items() if k == lambda_key)

    def _make_closure(self, info: FuncInfo, caps: list[tuple[str, VarInfo]], site: Node,
                      own: bool = False) -> str | None:
        for name, var in caps:
            if is_slice_type(var.ty):
                self._err(site, f"A lambda cannot capture the slice `{name}`.",
                          f"Pass `{name}` to the lambda as a parameter instead.")
                return None
            if own and var.ref_slot:
                self._err(site, f"A `Fn` closure cannot capture the reference `{name}`: it may outlive it.",
                          f"Capture the value instead: `{name}_copy = {name}.clone()` before the lambda.")
                return None
            if var.ty == ERR:
                return None
        decl: FuncDecl = info.decl  # type: ignore[assignment]
        name = CLOSURE_PREFIX + info.key
        fields = {n: v.ty for n, v in caps}
        if own:  # owned captures: heap values are moved in, everything else copied
            modes: dict[str, str] = {}
        else:
            modes = {n: "read" for n, v in caps if self._drop(v.ty) or v.ref_slot}
            modes.update({n: "lend" for n, _ in caps if self.capture_modes.get((info.key, n)) == "lend"})
        sdecl = _at(StructDecl(name, [_at(FieldDecl(n, TypeRef(t), mode=modes.get(n, ""),
                                                    tied_to="self" if n in modes else None), site)
                                      for n, t in fields.items()]), site)
        sinfo = StructInfo(name, fields, sdecl, field_modes=modes, field_tied={n: "self" for n in modes})
        sinfo.field_pub = {n: True for n in fields}  # only the compiler's code reads them, from any module
        self.structs[name] = sinfo
        self.type_order.append(name)
        self.closures[name] = info.key
        if own:
            self.owning_closures.add(name)
        self.lambda_caps[info.key] = [(n, v.ty) for n, v in caps]
        # Lifted function: `__env` first, captured names read through it.
        env = _at(Param(ENV, TypeRef(name), "read"), decl)
        env.ty = name  # type: ignore[attr-defined]
        env.fixed_ty = name  # type: ignore[attr-defined]
        decl.params.insert(0, env)
        info.params.insert(0, ParamInfo(ENV, name, "read", env))
        captured = set(fields)
        for n in list(_walk(decl.body)):
            if isinstance(n, Name) and n.name in captured:
                _replace(n, _at(FieldAccess(_at(Name(ENV), n), n.name), n))
            elif isinstance(n, Call) and not n.qualifier and n.callee in captured:
                _replace(n, _at(MethodCall(_at(Name(ENV), n), n.callee, n.args), n))
        return name

    def _capture_mode(self, name: str) -> str | None:
        """Field mode of captured `name` in the closure whose body is being checked."""
        if self.cur is None or not self.cur.params or self.cur.params[0].name != ENV:
            return None
        info = self.structs.get(self.cur.params[0].ty)
        return info.field_modes.get(name) if info is not None else None

    def _infer_capture(self, name: str) -> bool:
        """The lambda body changes captured `name`: record that it must be captured as `lend`.
        check_program re-checks the program with that capture mode."""
        if self.cur is None or not self._is_lambda(self.cur):
            return False
        if self.cur.params and self.cur.params[0].ty in self.owning_closures:
            return False  # a `Fn` closure owns copies: changing them would be invisible to the caller
        self.mode_upgrades[("capture", self.cur.key, name)] = "lend"
        return True

    # -- owned closures: `Fn(A) -> R` -------------------------------------------------------------
    def _box_into(self, expected: str, actual: str, node: Node) -> bool | None:
        """Converts a function value or a closure to the owned closure type `expected` (marks `node`).
        Returns None when `actual` is not convertible (the caller reports the mismatch)."""
        if is_fn_type(actual):
            sig = actual
        elif actual in self.closures:
            sig = self._closure_signature(actual)
        else:
            return None
        if fn_parts(sig) != fn_parts(expected):
            self._err(node, f"`{self._closure_display(actual)}` does not match `{expected}`.",
                      "Make the parameter and result types match.")
            return False
        info = self.structs.get(actual)
        if info is not None and info.field_modes:
            names = ", ".join(f"`{n}`" for n in info.field_modes)
            self._err(node, f"This closure borrows {names}, so it cannot become a `Fn` value that may outlive it.",
                      "Write the lambda where the `Fn` is expected (a parameter, a `return`, or `f: Fn(...) = ...`): "
                      "it then owns what it captures.")
            return False
        if self._drop(actual) and self._is_place_expr(node):  # the closure's owned captures move along
            if not self._check_move(node, node):  # type: ignore[arg-type]
                return False
            node.is_move = True  # type: ignore[attr-defined]
        node.box_fn = expected  # type: ignore[attr-defined]
        return True

    @staticmethod
    def _captured_place(place: Node) -> str | None:
        """`v` when `place` is (inside) a captured variable `__env.v` of a lambda body."""
        e = place
        while isinstance(e, FieldAccess) or hasattr(e, "obj") and type(e).__name__ in ("IndexAccess", "SliceExpr"):
            if isinstance(e, FieldAccess) and isinstance(e.obj, Name) and e.obj.name == ENV:
                return e.field_name
            e = e.obj  # type: ignore[attr-defined]
        return None

    # -- calling a closure ----------------------------------------------------------------------
    def _closure_call(self, e: Call | MethodCall, target: Node, closure: str) -> str:
        """`f(x)` where `f` is a closure: call the lifted function with `f` as `__env`."""
        key = self.closures[closure]
        info = self.funcs[key]
        call = _at(Call(info.decl.name, [target] + list(e.args)), e)
        _replace(e, call)
        e.func_key = key  # type: ignore[attr-defined]
        if info.is_instance:  # the lambda of one instance of a generic function
            e.inst_key = key  # type: ignore[attr-defined]
        self._check_args(e, info.decl.name, info.params, e.args, None)  # type: ignore[arg-type]
        return info.ret

    def _closure_signature(self, closure: str) -> str:
        info = self.funcs[self.closures[closure]]
        return make_fn([p.ty for p in info.params[1:]], info.ret)

    def _closure_display(self, ty: str) -> str:
        return f"closure {self._closure_signature(ty)}" if ty in self.closures else ty

    # -- passing a closure where a function value is expected ---------------------------------
    def _closure_arg(self, arg: Node) -> str | None:
        """Closure type of `arg` without checking it twice: a closure variable or a capturing lambda."""
        if isinstance(arg, StructLit):  # a lambda already turned into its closure value
            return arg.type_name if arg.type_name in self.closures else None
        if not isinstance(arg, Name):
            return None
        var = self._lookup(arg.name)
        if var is not None:
            return var.ty if var.ty in self.closures else None
        info = self._generic_lambda(arg.name, arg) or self._visible_func(arg.name)
        if not self._is_lambda(info):
            return None
        if info.key in self.lambda_caps:  # type: ignore[union-attr]
            return self._closure_of(info.key)  # type: ignore[union-attr]
        caps = self._captures(info)  # type: ignore[arg-type]
        return self._make_closure(info, caps, arg) if caps else None  # type: ignore[arg-type]

    def _specialize_for_closures(self, info: FuncInfo, args: list[Node], call: Node, offset: int = 0) -> FuncInfo:
        """A copy of `info` whose function-typed parameters take the closures passed at this call.
        `offset` skips leading parameters that have no argument in `args` (a method's `self`)."""
        if info.is_extern or len(args) != len(info.params) - offset:
            return info
        chosen: dict[int, str] = {}
        for i, (p, a) in enumerate(zip(info.params[offset:], args), offset):
            if is_fn_type(p.ty):
                closure = self._closure_arg(a)
                if closure is not None:
                    want = p.ty
                    have = self._closure_signature(closure)
                    if have != want:
                        self._err(a, f"Closure `{have}` does not match parameter `{p.name}: {want}`.",
                                  "Make the lambda's parameter and result types match.")
                        return info
                    chosen[i] = closure
        if not chosen:
            return info
        key = make_generic(info.key, [chosen.get(i, "_") for i in range(len(info.params))])
        existing = self.funcs.get(key)
        if existing is not None:
            return existing
        if not self._enter_instantiation(call):
            return info
        d = copy.deepcopy(info.decl)
        d.inst_key = key  # type: ignore[union-attr]
        for i, closure in chosen.items():
            d.params[i].fixed_ty = closure  # type: ignore[union-attr]
        saved = self.tparams
        self.tparams = dict(info.bindings)  # a generic instance: its type parameters stay bound
        try:
            inst = self._declare_function(d, key, instance=True)  # type: ignore[arg-type]
        finally:
            self.tparams = saved
            self.depth -= 1
        if inst is None:
            return info
        inst.bindings = dict(info.bindings)
        inst.is_instance = True
        inst.depth = self.depth + 1
        self.instances.append(d)  # type: ignore[arg-type]
        self.pending.append(inst)
        return inst

