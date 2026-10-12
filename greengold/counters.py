"""Counters that cannot overflow inside a loop with constant bounds.

`n = 0` followed by `for i in 0..N:` whose body only adds constants to `n` (`n += 1`, perhaps under an `if`)
leaves `n` at most `N * (sum of the constants)` when the loop ends. When that fits the counter's type, the
overflow check of those additions can never fire, and dropping it matters: the check is a branch to a panic,
which keeps LLVM from turning `if c: n += 1` into a branch-free select. With data-dependent conditions the
branch is mispredicted often.

The analysis is deliberately narrow. The counter must be declared with an integer literal in the same block
right before the loop (no statement in between mentions it), the loop body may mention it only as the target
of `+= literal`, in arithmetic, or in a condition, never inside a nested loop, and the function must not
contain lambdas (a closure could change the counter through a `lend` call). Marked assignments get
`in_range = True`; the code generator then emits a plain `add nsw`/`add nuw`.
"""
from __future__ import annotations

from dataclasses import fields

from .ast_nodes import (Assign, Binary, Branch, For, ForIn, FuncDecl, If, IntLit, Name, Node, Unary, VarDecl,
                        While)
from .typeinfo import INT_RANGES


def _children(node: object):
    for f in fields(node):  # type: ignore[arg-type]
        v = getattr(node, f.name)
        if isinstance(v, Node):
            yield v
        elif isinstance(v, list):
            for x in v:
                if isinstance(x, Node):
                    yield x
                elif isinstance(x, tuple):
                    yield from (y for y in x if isinstance(y, Node))


def _mentions(node: Node, name: str) -> bool:
    if isinstance(node, Name) and node.name == name:
        return True
    if isinstance(node, VarDecl) and node.name == name:
        return True
    return any(_mentions(c, name) for c in _children(node))


def _has_lambda(node: Node) -> bool:
    if isinstance(node, Name) and node.name.startswith("__lambda_"):
        return True
    return any(_has_lambda(c) for c in _children(node))


def _int_lit(e: object) -> int | None:
    if isinstance(e, IntLit) and not isinstance(e.value, bool):
        return e.value
    if isinstance(e, Unary) and e.op == "-" and isinstance(e.operand, IntLit):
        return -e.operand.value
    return None


def _trip_count(s: For) -> int | None:
    bounds = getattr(s, "const_bounds", None)
    if bounds is None:
        return None
    lo, hi = bounds
    step = s.step_value
    span = (hi - lo if step > 0 else lo - hi) + (1 if s.inclusive else 0)
    return max(0, -(-span // abs(step)))


def _scan(node: Node, parent: Node | None, name: str, adds: list[Assign], in_loop: bool) -> bool:
    """Collect `name += literal` in `node`; False when `name` is used in any other way."""
    if isinstance(node, VarDecl) and node.name == name:
        return False  # shadowed inside the loop
    if isinstance(node, Assign) and isinstance(node.target, Name) and node.target.name == name:
        k = _int_lit(node.value)
        if node.op != "+=" or k is None or k < 0 or in_loop:
            return False
        adds.append(node)
        return True
    if isinstance(node, Name) and node.name == name:
        return isinstance(parent, (Binary, Unary)) or (isinstance(parent, Branch) and node is parent.cond)
    nested = in_loop or isinstance(node, (For, ForIn, While))
    return all(_scan(c, node, name, adds, nested) for c in _children(node))


def _mark_block(stmts: list) -> None:
    for j, s in enumerate(stmts):
        if isinstance(s, For):
            trip = _trip_count(s)
            if trip is not None:
                _mark_loop(stmts, j, s, trip)
        _mark_node(s)


def _mark_node(node: Node) -> None:
    for f in fields(node):  # type: ignore[arg-type]
        v = getattr(node, f.name)
        if isinstance(v, list) and v and all(isinstance(x, Node) for x in v):
            _mark_block(v)
        elif isinstance(v, Node):
            _mark_node(v)


def _mark_loop(stmts: list, j: int, loop: For, trip: int) -> None:
    for i in range(j - 1, -1, -1):
        decl = stmts[i]
        if not isinstance(decl, VarDecl):
            continue
        name, start, ty = decl.name, _int_lit(decl.value), decl.ty
        if start is None or ty not in INT_RANGES or decl.ref_mode or name == loop.var:
            continue
        if any(_mentions(stmts[k], name) for k in range(i + 1, j)):
            continue  # changed (or read) between its declaration and the loop
        adds: list[Assign] = []
        if not all(_scan(b, None, name, adds, False) for b in loop.body) or not adds:
            continue
        lo, hi = INT_RANGES[ty]
        if lo <= start and start + trip * sum(_int_lit(a.value) or 0 for a in adds) <= hi:
            for a in adds:
                a.in_range = True  # type: ignore[attr-defined]


def mark_bounded_counters(f: FuncDecl) -> None:
    if any(_has_lambda(s) for s in f.body):
        return
    _mark_block(f.body)
