"""Borrow checker: `consume` / `read` / `lend` rules and `tied to` lifetime bounds.

Type checking (`typecheck.py`) catches call-site conflicts (two `lend`s in the same call, `lend` + `read`)
and use-after-move (`MoveAnalyzer`). This module checks references STORED IN A VARIABLE:

  * Validity of `tied to` bounds (parameter name / `self`).
  * When a struct with reference fields (`owner: read Player tied to self`) is instantiated as a value,
    the "holder" variable is bound to the referenced variable (referent):
      - `read` bond: referent cannot be moved / modified / reassigned while the holder is still to be used.
      - `lend` bond: no other access to the referent can occur while the holder is live (exclusive write permission).
  * References tied to local / value / `consume` variables are forbidden from escaping the function (dangling).
  * Views carried by value are tracked the same way: a `str` or slice (or a value holding one, such as
    `List[str]` or a struct with a `str` field) made from a heap-owning variable (`s.as_str()`,
    `text[1..3]`, `string.split(text, ",")`) ties the variable or container that stores it to that
    variable with a `read` bond. String literals are static and tie nothing.

"Still in use" is liveness (`flow.Liveness`): a holder keeps its referent from its tie to its last use
on some path, through branches and loop back edges; a holder given a new value before its next use no
longer holds the old referent. Loop bodies are checked with the ties a previous iteration made.

Rule summary:
    consume  -> single owner; memory cleaned up at end of scope.
    read     -> unlimited concurrent reads; forbidden while `lend` is active.
    lend     -> only ONE at a time; no other `read` permitted concurrently.
    tied to  -> reference cannot outlive what it is tied to.
"""
from __future__ import annotations

from dataclasses import dataclass, fields as dc_fields

from .ast_nodes import (
    walk,
    FieldInit, StrLit,
    Assign, BorrowExpr, Call, Defer, Expr, ExprStmt, FieldAccess, For, ForIn, FuncDecl, If, IndexAccess, Match,
    MethodCall, Name, Node, Program, Return, SliceExpr, Stmt, StructDecl, StructLit, VarDecl, While, Yield, unparse,
)
from .diagnostics import DiagnosticBag, Fix, Label, Note
from .flow import Liveness
from .typeinfo import generic_parts, is_array_type, is_slice_type, needs_drop


@dataclass
class Holder:
    """A local variable holding a value with reference fields."""
    name: str
    refs: list[tuple[str, str, Node]]  # (referent root name, "read" | "lend", initialization node)


def _walk(node):
    return walk(node)


def _root(e: Expr) -> str | None:
    while isinstance(e, (FieldAccess, IndexAccess, SliceExpr)):
        e = e.obj
    return e.name if isinstance(e, Name) else None


class BorrowChecker:
    def __init__(self, program: Program, diags: DiagnosticBag) -> None:
        self.program = program
        self.diags = diags
        self.current_filename: str | None = None
        self.reported: set[tuple] = set()
        self.cur: FuncDecl | None = None
        self.local_kinds: dict[str, str] = {}  # variable name -> "param-read" | "param-consume" | "owner"
        self.bound: dict[str, Node] = {}
        # View-flow summary of each function (keyed by `id(FuncDecl)`): (i, j) means the call leaves a view
        # of argument j's memory inside argument i (`out.push(s.as_str())`).
        # The receiver of a method is argument 0. Computed to a fixpoint before diagnostics are reported.
        self.summaries: dict[int, set[tuple[int, int]]] = {}
        self.has_self: dict[int, bool] = {}
        self.silent = False

    # -- reporting ---------------------------------------------------------
    def _error(self, node: Node, msg: str, hint: str | None = None, notes: list[Note] | None = None, *,
               rule: str | None = None, labels: list[Label] | None = None,
               details: dict | None = None, fixes: list[Fix] | None = None) -> None:
        if self.silent:
            return
        fname = getattr(node, "filename", None) or self.current_filename
        key = (fname, node.line, node.col, msg)
        if key in self.reported:
            return
        self.reported.add(key)
        self.diags.error(msg, node.line, node.col, max(node.length, 1), hint, notes or [], filename=fname,
                         rule=rule, labels=labels, details=details, fixes=fixes)

    def _decl_label(self, name: str) -> list[Label]:
        node = self.bound.get(name)
        if node is None:
            return []
        return [Label("definition", f"`{name}` is declared here", node.line, node.col, max(node.length, 1),
                      getattr(node, "filename", None))]

    # -- entry -------------------------------------------------------------
    def run(self) -> None:
        own_funcs = [d for d in self.program.decls if isinstance(d, FuncDecl)]
        # core.gg is typechecked as the prelude (`from_prelude`), but those bodies are the
        # source under edit and must still be borrow-checked. User programs only carry
        # prelude copies inside `func_instances`, which stay skipped.
        checking_prelude = bool(own_funcs) and all(d.from_prelude for d in own_funcs)
        for d in self.program.decls:
            if isinstance(d, StructDecl):
                self._check_struct(d)
        funcs = [d for d in list(self.program.decls) + list(self.program.func_instances)
                 if isinstance(d, FuncDecl) and not d.type_params and not d.owner_params]
        # Summaries first, without reporting: a caller needs its callees' summaries, and recursion
        # needs a fixpoint. Summaries only grow, so this terminates.
        self.silent = True
        # Only a function with a `lend` parameter that can hold a view can leave one behind.
        holders = [d for d in funcs if any(p.mode == "lend" and self._viewish(getattr(p, "ty", None))
                                           for p in d.params)]
        for _ in range(16):
            before = {k: set(v) for k, v in self.summaries.items()}
            for d in holders:
                self.current_filename = getattr(d, "filename", None)
                self._check_func(d)
            if before == self.summaries:
                break
        self.silent = False
        for d in funcs:
            if d.from_prelude and not checking_prelude:
                continue
            self.current_filename = getattr(d, "filename", None)
            self._check_func(d)

    # -- declaration checks ---------------------------------------------
    def _check_struct(self, d: StructDecl) -> None:
        self.current_filename = getattr(d, "filename", None)
        for f in d.fields:
            if f.mode and f.tied_to not in (None, "self"):
                self._error(f, f"Field `{f.name}` specifies `tied to {f.tied_to}`, but fields can only be tied to `self`.",
                            f"Write `{f.name}: {f.mode} {f.type_ref.name} tied to self`.",
                            rule="bad-tied-to", details={"name": f.name, "tied_to": f.tied_to})

    def _check_func(self, d: FuncDecl) -> None:
        self.cur = d
        names = [p.name for p in d.params]
        for p in d.params:
            if p.tied_to is None:
                continue
            if p.tied_to == p.name:
                self._error(p, f"`{p.name}` cannot be tied to itself.", "Tie to another parameter.",
                            rule="bad-tied-to", details={"name": p.name, "tied_to": p.tied_to})
            elif p.tied_to not in names:
                self._error(p, f"`tied to {p.tied_to}`: no parameter named `{p.tied_to}`.",
                            f"Parameters: {', '.join(names) or '(none)'}.",
                            rule="bad-tied-to", details={"name": p.name, "tied_to": p.tied_to})
            else:
                target = next(q for q in d.params if q.name == p.tied_to)
                if target.mode == "":
                    self._error(p, f"`{p.name}` cannot be tied to a value parameter (`{target.name}`): it will be destroyed when the function returns.",
                                f"Make parameter `{target.name}` `read` or `lend`.",
                                rule="bad-tied-to",
                                labels=[Label("definition", f"`{target.name}` is a value parameter",
                                              target.line, target.col, max(target.length, 1),
                                              getattr(target, "filename", None))],
                                details={"name": p.name, "tied_to": p.tied_to})
        self.local_kinds = {}
        self.var_depth: dict[str, int] = {}
        self.ref_ties: dict[str, str] = {}
        self.bound = {p.name: p for p in d.params}
        for p in d.params:
            self.local_kinds[p.name] = {"read": "ref", "lend": "ref"}.get(p.mode, "owner")
            self.var_depth[p.name] = 0
        holders: dict[str, Holder] = {}
        self.live = Liveness(d.body)
        self._block(d.body, holders, 1)
        self._summarize(holders)

    def _summarize(self, holders: dict[str, Holder]) -> None:
        """Records which parameters hold a view of another parameter's memory at this exit."""
        d = self.cur
        if d is None or not self.silent:
            return
        index = {p.name: i for i, p in enumerate(d.params)}
        self.has_self[id(d)] = bool(d.params) and d.params[0].name == "self"
        out = self.summaries.setdefault(id(d), set())
        for name, i in index.items():
            h = holders.get(name)
            if h is None:
                continue
            for root, _mode, _node in h.refs:
                j = index.get(root)
                if j is not None and j != i:
                    out.add((i, j))

    # -- body traversal -----------------------------------------------------
    def _block(self, stmts: list[Stmt], holders: dict[str, Holder], depth: int) -> None:
        for s in stmts:
            self._stmt(s, holders, depth)

    def _stmt(self, s: Stmt, holders: dict[str, Holder], depth: int) -> None:
        after = self.live.after.get(id(s), frozenset())
        live = self.live.after_head.get(id(s), after) if isinstance(s, (If, While, For, ForIn, Match)) else after
        # The nodes this statement evaluates itself: its headers. The bodies of an `if`, a loop, or a
        # `match` are their own statements, checked when they are reached.
        heads = [(header, list(_walk(header))) for header in self._headers(s)]
        for header, nodes in heads:
            self._invalidations(header, s, holders, live, nodes)
        flat = [n for _, nodes in heads for n in nodes]
        self._drop_moved(flat, holders)
        self._store_views(s, holders, flat)
        if isinstance(s, VarDecl):
            self.var_depth[s.name] = depth
            self._bind_var(s, holders)
        elif isinstance(s, Assign) and s.op == "=" and isinstance(s.target, Name):
            self._bind_assign(s, holders)
        elif isinstance(s, Assign) and getattr(s, "rebind", False) and isinstance(s.target, FieldAccess):
            owner = self._root_name(s.target.obj)
            if owner and s.ref_root:
                h = holders.get(owner)
                if h is None:
                    h = Holder(owner, [])
                    holders[owner] = h
                h.refs.append((s.ref_root, s.ref_mode or "read", s))
                self._escape(owner, h, s)
        elif isinstance(s, Return) and s.value is not None:
            self._check_return(s, holders)
        if isinstance(s, Return):
            self._summarize(holders)
        if isinstance(s, If):
            results = [self._branch(br.body, holders, depth) for br in s.branches]
            if s.else_body is not None:
                results.append(self._branch(s.else_body, holders, depth))
            else:
                results.append(holders)
            self._merge_holders(holders, results, outer=depth)
        elif isinstance(s, (While, For, ForIn)):
            # Twice: ties made by one iteration are in place when the next iteration runs.
            local = self._branch(s.body, holders, depth, silent=True)
            entry = {k: Holder(v.name, list(v.refs)) for k, v in holders.items()}
            self._merge_holders(entry, [holders, local], keep_new=True)
            local = self._branch(s.body, entry, depth)
            self._merge_holders(holders, [holders, local], keep_new=True)
        elif isinstance(s, Match):
            results = [self._branch(arm.body, holders, depth) for arm in s.arms]
            if results:
                self._merge_holders(holders, results, outer=depth)

    def _branch(self, body: list[Stmt], holders: dict[str, Holder], depth: int,
                silent: bool = False) -> dict[str, Holder]:
        local = {k: Holder(v.name, list(v.refs)) for k, v in holders.items()}
        was = self.silent
        self.silent = was or silent
        try:
            self._block(body, local, depth + 1)
        finally:
            self.silent = was
        return local

    def _merge_holders(self, holders: dict[str, Holder], results: list[dict[str, Holder]],
                       keep_new: bool = False, outer: int | None = None) -> None:
        if keep_new:  # a holder that only the loop body created still holds after the loop
            for res in results:
                for name, h in res.items():
                    if name not in holders:
                        holders[name] = Holder(h.name, [])
        elif outer is not None:
            # A branch gave a variable of the enclosing scope its first view (`v = s.as_str()` in an `if`
            # when `v` held a literal before): the tie stays after the branch. The branch's own locals do not.
            for res in results:
                for name, h in res.items():
                    if name not in holders and self.var_depth.get(name, 0) <= outer:
                        holders[name] = Holder(h.name, [])
        for name, h in list(holders.items()):
            seen: set[tuple[str, str]] = set()
            merged: list[tuple[str, str, Node]] = []
            for res in results:
                src = res.get(name)
                if src is None:
                    continue
                for item in src.refs:
                    key = (item[0], item[1])
                    if key not in seen:
                        seen.add(key)
                        merged.append(item)
            h.refs = merged

    def _bind_var(self, s: VarDecl, holders: dict[str, Holder]) -> None:
        self.bound[s.name] = s
        if s.ref_mode:
            self.local_kinds[s.name] = "ref"
            if s.ref_root:
                self.ref_ties[s.name] = s.ref_root
            h = Holder(s.name, self._refs_from(s.value, s.ref_mode, s, holders) or (
                [(s.ref_root, s.ref_mode, s)] if s.ref_root else []))
            self._escape(s.name, h, s)
            holders[s.name] = h
            return
        self.local_kinds[s.name] = "owner"
        h = self._make_holder(s.name, s.value, holders)
        if h is None and isinstance(s.value, Name) and s.value.name in holders and not getattr(s.value, "is_move", False):
            h = Holder(s.name, list(holders[s.value.name].refs))
        h = self._with_views(s.name, h, s.value, holders)
        if h is not None:
            self._escape(s.name, h, s)
            holders[s.name] = h

    def _bind_assign(self, s: Assign, holders: dict[str, Holder]) -> None:
        name = s.target.name  # type: ignore[union-attr]
        if getattr(s, "rebind", False):
            if s.ref_root:
                self.ref_ties[name] = s.ref_root
            h = Holder(name, self._refs_from(s.value, s.ref_mode or "read", s, holders) or (
                [(s.ref_root, s.ref_mode or "read", s)] if s.ref_root else []))
            self._escape(name, h, s)
            holders[name] = h
            return
        h = self._make_holder(name, s.value, holders)
        if h is None and isinstance(s.value, Name) and s.value.name in holders and not getattr(s.value, "is_move", False):
            h = Holder(name, list(holders[s.value.name].refs))
        h = self._with_views(name, h, s.value, holders)
        if h is not None:
            self._escape(name, h, s)
            holders[name] = h
        elif self._viewish(getattr(s.value, "ty", None)):
            holders.pop(name, None)  # now holds a view of nothing owned (a literal)

    def _with_views(self, name: str, h: Holder | None, value: Expr, holders: dict[str, Holder]) -> Holder | None:
        refs = self._view_refs(value, holders)
        if not refs:
            return h
        h = h or Holder(name, [])
        known = {(r[0], r[1]) for r in h.refs}
        h.refs = h.refs + [r for r in refs if (r[0], r[1]) not in known]
        return h

    @staticmethod
    def _headers(s: Stmt) -> list[Node]:
        if isinstance(s, If):
            return [br.cond for br in s.branches]
        if isinstance(s, While):
            return [s.cond]
        if isinstance(s, For):
            return [s.start, s.end]
        if isinstance(s, ForIn):
            return [s.iterable]
        if isinstance(s, Match):
            return [s.scrutinee]
        return [s]

    # -- views carried by value (`str`, slices) -----------------------------
    def _viewish(self, ty: object, seen: frozenset[str] = frozenset()) -> bool:
        """Can a value of `ty` point into memory owned by a variable (`str`, slice, or a type holding one)?"""
        if not isinstance(ty, str) or ty in seen:
            return False
        if ty == "str" or is_slice_type(ty):
            return True
        seen = seen | {ty}
        parts = generic_parts(ty)
        if parts is not None and any(self._viewish(a, seen) for a in parts[1]):
            return True
        si = self.program.struct_infos.get(ty)
        if si is not None:
            if si.field_modes:  # `who: read P tied to self`: the value points at a variable
                return True
            return any(self._viewish(t, seen) for n, t in si.fields.items() if n not in si.field_modes)
        ei = self.program.enum_infos.get(ty)
        if ei is not None:
            return any(self._viewish(t, seen) for v in ei.variants.values() for t in v.payload)
        return False

    def _holds_ref(self, ty: object, seen: frozenset[str] = frozenset()) -> bool:
        """Does a value of `ty` hold a reference field (`read T tied to self`), directly or inside?"""
        if not isinstance(ty, str) or ty in seen:
            return False
        si = self.program.struct_infos.get(ty)
        if si is None:
            return False
        return bool(si.field_modes) or any(self._holds_ref(t, seen | {ty}) for t in si.fields.values())

    def _owns_heap(self, ty: object) -> bool:
        return isinstance(ty, str) and needs_drop(ty, self.program.struct_infos, self.program.enum_infos)

    def _view_refs(self, e: object, holders: dict[str, Holder]) -> list[tuple[str, str, Node]]:
        """Variables whose memory the value of `e` may point into (only for view types)."""
        if not isinstance(e, Node) or not self._viewish(getattr(e, "ty", None)):
            return []
        return self._view_sources(e, holders)

    def _view_sources(self, e: Node, holders: dict[str, Holder]) -> list[tuple[str, str, Node]]:
        if isinstance(e, StrLit):
            return []
        if isinstance(e, Name):
            return list(holders[e.name].refs) if e.name in holders else []
        out: list[tuple[str, str, Node]] = []
        if isinstance(e, (Call, MethodCall)) and self._holds_ref(getattr(e, "ty", None)):
            # `m.lock()` returns a struct with a reference field: it may point at any `read`/`lend` argument
            lent = list(zip(e.args, getattr(e, "arg_modes", []) or []))
            if isinstance(e, MethodCall) and getattr(e, "self_mode", "") in ("read", "lend"):
                lent.append((e.obj, e.self_mode))
            for arg, mode in lent:
                root = self._root_name(arg) if isinstance(arg, (Name, FieldAccess, IndexAccess)) else None
                if root and mode in ("read", "lend"):
                    out.append((root, mode, arg))
        for f in dc_fields(e):
            if f.name in ("ty", "inst_note"):
                continue
            val = getattr(e, f.name)
            for child in (val if isinstance(val, list) else [val]):
                if isinstance(child, FieldInit):
                    child = child.value
                if not isinstance(child, Expr) or getattr(child, "is_move", False):
                    continue  # a moved value is owned by the result, not borrowed
                cty = getattr(child, "ty", None)
                root = self._root_name(child) if isinstance(child, (Name, FieldAccess, IndexAccess)) else None
                through = self._slice_base(child)
                if through is not None:  # `names[0].as_str()` of a `[]string`: points where `names` points
                    out.extend(self._view_sources(through, holders))
                elif root and isinstance(e, SliceExpr) and child is e.obj and isinstance(cty, str) and is_array_type(cty):
                    out.append((root, "read", child))  # `xs[1..3]` of an array: points into `xs`'s own memory
                elif root and self._owns_heap(cty) and not self._viewish(cty):
                    out.append((root, "read", child))  # `s.as_str()`: points into `s`
                elif self._viewish(cty):
                    out.extend(self._view_sources(child, holders))
                elif root and self._owns_heap(cty):
                    out.append((root, "read", child))
        return out

    @staticmethod
    def _slice_base(e: object) -> Expr | None:
        """The slice an element place is reached through (`xs` in `xs[i].name`), or None."""
        while isinstance(e, (FieldAccess, IndexAccess)):
            base = e.obj
            if isinstance(e, IndexAccess) and is_slice_type(getattr(base, "ty", None) or ""):
                return base
            e = base
        return None

    def _store_views(self, s: Stmt, holders: dict[str, Holder], nodes: list[Node]) -> None:
        """A view stored inside a container (`names.push(s.as_str())`, `p.name = t`, a `lend` argument)
        ties the container's variable to the view's sources."""
        targets: list[tuple[Expr, list[Expr]]] = []
        if isinstance(s, Assign) and not isinstance(s.target, Name) and not getattr(s, "rebind", False):
            targets.append((s.target, [s.value]))
        for n in nodes:
            if isinstance(n, (Call, MethodCall)):
                modes = list(getattr(n, "arg_modes", []) or [])
                lent = [a for a, m in zip(n.args, modes) if m == "lend"]
                if isinstance(n, MethodCall) and n.self_mode == "lend":
                    lent.append(n.obj)
                others = [a for a in n.args if not any(a is x for x in lent)]
                for target in lent:
                    targets.append((target, others))
        explicit: list[tuple[Expr, list[tuple[str, str, Node]]]] = []
        for n in nodes:
            cid = getattr(n, "callee_id", None) if isinstance(n, (Call, MethodCall)) else None
            summary = self.summaries.get(cid or 0)
            if not summary:
                continue
            argv = ([n.obj] if isinstance(n, MethodCall) and self.has_self.get(cid or 0) else []) + list(n.args)
            for i, j in summary:
                if i >= len(argv) or j >= len(argv):
                    continue
                src = argv[j]
                refs = self._view_refs(src, holders)
                root = self._root_name(src)
                if not refs and root and self._owns_heap(getattr(src, "ty", None)):
                    refs = [(root, "read", src)]  # the callee stored `src.as_str()`
                if refs:
                    explicit.append((argv[i], refs))
        for target, values in targets:
            if not self._viewish(getattr(target, "ty", None)):
                continue  # `buf.append_str(s.as_str())`: a `string` copies the bytes, it cannot keep the view
            refs = [r for v in values for r in self._view_refs(v, holders)]
            explicit.append((target, refs))
        for target, refs in explicit:
            if not self._viewish(getattr(target, "ty", None)):
                continue
            root = self._root_name(target)
            if not refs or not root:
                continue
            h = holders.get(root)
            if h is None:
                h = Holder(root, [])
                holders[root] = h
            known = {(r[0], r[1]) for r in h.refs}
            h.refs.extend(r for r in refs if (r[0], r[1]) not in known and r[0] != root)
            self._escape(root, h, s)

    # -- holder creation ---------------------------------------------------
    def _make_holder(self, name: str, value: Expr, holders: dict[str, Holder]) -> Holder | None:
        if not isinstance(value, StructLit):
            return None
        refs: list[tuple[str, str, Node]] = []
        for f in value.fields:
            if not f.ref_mode:
                continue
            refs.extend(self._refs_from(f.value, f.ref_mode, f, holders))
        return Holder(name, refs) if refs else None

    def _refs_from(self, value: Expr, mode: str, node: Node, holders: dict[str, Holder]) -> list[tuple[str, str, Node]]:
        root = self._root_name(value)
        if root and root in holders and holders[root].refs:
            return list(holders[root].refs)
        if root:
            return [(root, mode, node)]
        return []

    def _escape(self, holder_name: str, h: Holder, node: Node) -> None:
        hd = self.var_depth.get(holder_name, 0)
        for root, _mode, src in h.refs:
            rd = self.var_depth.get(root)
            if rd is not None and rd > hd:
                where = src or node
                self._error(where, f"`{root}` does not live long enough for `{holder_name or 'this value'}` to reference it.",
                            f"`{root}` is declared in an inner scope; borrow a value from the outer scope.",
                            rule="reference-escapes", labels=self._decl_label(root),
                            details={"referent": root, "holder": holder_name or ""})

    def _check_return(self, s: Return, holders: dict[str, Holder]) -> None:
        refs: list[tuple[str, str, Node]] = []
        if isinstance(s.value, StructLit):
            h = self._make_holder("", s.value, holders)
            refs = h.refs if h else []
        elif isinstance(s.value, Name) and s.value.name in holders and not (self.cur is not None and self.cur.ret_view):
            refs = holders[s.value.name].refs
        if not (self.cur is not None and self.cur.ret_view):
            refs = list(refs) + [r for r in self._view_refs(s.value, holders) if r not in refs]
        for root, _mode, node in refs:
            if self.local_kinds.get(root, "owner") == "owner":
                self._error(
                    node, f"`{root}` is destroyed upon returning from the function; a reference tied to it cannot be returned.",
                    f"Make `{root}` a `read`/`lend` parameter or copy the value (`copy`).",
                    rule="reference-escapes", labels=self._decl_label(root),
                    details={"referent": root, "holder": ""})

    def _drop_moved(self, nodes: list[Node], holders: dict[str, Holder]) -> None:
        for n in nodes:
            if isinstance(n, Name) and getattr(n, "is_move", False):
                holders.pop(n.name, None)

    def _root_name(self, e: Expr | None) -> str | None:
        if e is None:
            return None
        marked = getattr(e, "tie_root", None)
        if marked and not isinstance(e, (Name, FieldAccess, IndexAccess, SliceExpr, BorrowExpr)):
            return marked
        while isinstance(e, BorrowExpr):
            e = e.expr
        while isinstance(e, (FieldAccess, IndexAccess, SliceExpr)):
            e = e.obj  # type: ignore[assignment]
        if isinstance(e, (Call, MethodCall)):
            return getattr(e, "tie_root", None)
        if isinstance(e, Name):
            name = e.name
            seen: set[str] = set()
            while name in self.ref_ties and name not in seen:
                seen.add(name)
                nxt = self.ref_ties[name]
                if not nxt or nxt == name:
                    break
                name = nxt
            return name
        return None

    # -- invalidation -----------------------------------------------------
    def _invalidations(self, node: Node, stmt: Stmt, holders: dict[str, Holder], used_later: frozenset[str],
                       nodes: list[Node]) -> None:
        if not holders:
            return
        used_here = {n.name for n in nodes if isinstance(n, Name)}
        events = self._events(nodes)
        for h in holders.values():
            if h.name not in used_later and h.name not in used_here:
                continue
            for root, mode, init in h.refs:
                for kind, ev_root, ev_node in events:
                    if ev_root != root:
                        continue
                    if h.name not in used_later and kind not in ("lend", "move"):
                        continue  # used only in this statement: just a `lend` or move next to it conflicts
                    if kind == "use" and mode == "read":
                        continue
                    if kind == "use" and ev_node is init:
                        continue
                    if mode == "read":
                        verb = {"move": "is moved (`consume`)", "lend": "is borrowed as `lend`",
                                "assign": "is reassigned"}[kind]
                        msg = f"`{root}` {verb}, but `{h.name}` is still tied to it (`read`) and still in use."
                        hint = f"Finish using `{h.name}` first or defer mutating `{root}`."
                    else:
                        msg = (f"`{root}` is borrowed as `lend` by `{h.name}`; "
                               f"no other access is permitted while `{h.name}` is live.")
                        hint = f"Access `{root}` after finishing with `{h.name}`."
                    self._error(ev_node, msg, hint,
                                notes=[Note(init.line, init.col, max(init.length, 1),
                                            f"`{h.name}` was tied to `{root}` here")],
                                rule="borrow-invalidated",
                                labels=[Label("cause", f"`{h.name}` was tied to `{root}` here",
                                              init.line, init.col, max(init.length, 1),
                                              getattr(init, "filename", None))] + self._decl_label(root),
                                details={"referent": root, "holder": h.name, "bond": mode, "event": kind})

    def _events(self, nodes: list[Node]) -> list[tuple[str, str, Node]]:
        out: list[tuple[str, str, Node]] = []
        for n in nodes:
            if isinstance(n, (Name, FieldAccess)) and getattr(n, "is_move", False):
                r = self._root_name(n)
                if r:
                    out.append(("move", r, n))
            if isinstance(n, (Call, MethodCall)):
                for a, m in zip(n.args, n.arg_modes):
                    if m == "lend":
                        r = self._root_name(a)
                        if r:
                            out.append(("lend", r, a))
                if isinstance(n, MethodCall) and n.self_mode == "lend":
                    r = self._root_name(n.obj)
                    if r:
                        out.append(("lend", r, n))
            if isinstance(n, BorrowExpr) and n.mode == "lend":
                r = self._root_name(n.expr)
                if r:
                    out.append(("lend", r, n))
            if isinstance(n, VarDecl) and n.ref_mode == "lend" and n.ref_root:
                out.append(("lend", n.ref_root, n))
            if isinstance(n, Assign) and getattr(n, "rebind", False) and n.ref_mode == "lend" and n.ref_root:
                out.append(("lend", n.ref_root, n))
            elif isinstance(n, Assign):
                r = self._root_name(n.target)
                if r:
                    out.append(("assign", r, n))
            if isinstance(n, Name):
                out.append(("use", n.name, n))
        return out


def check_borrows(program: Program, diags: DiagnosticBag) -> None:
    BorrowChecker(program, diags).run()
