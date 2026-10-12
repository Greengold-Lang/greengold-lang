"""Control flow facts over a function body: which local names are live after each statement.

A name is live at a point when some path from that point reads it before it is given a new value.
The body is structured (no `goto`), so the analysis walks the statements backwards and runs each loop
to a fixpoint, with `break` going to the statement after the loop and `continue` to the loop head.
This is the liveness that "non-lexical" borrows need: a reference stops holding its referent at its
last use, not at the end of its scope, and a reference that is given a new value before its next use
no longer holds the old referent.

    live = Liveness(func.body)
    live.after[id(stmt)]    # names live after `stmt` runs
    live.after_head[id(s)]  # for if/while/for/match: names live after the header (condition, range,
                            # scrutinee) is evaluated, before a branch or the body runs
"""
from __future__ import annotations

from dataclasses import fields as dc_fields

from .ast_nodes import (
    walk,
    Assign, Break, Call, Continue, Defer, ExprStmt, For, ForIn, If, Match, Name, Node, Return, Stmt, VarDecl, While,
    Wrapping, Yield,
)


def _walk(node):
    return walk(node)


def uses(node) -> frozenset[str]:
    """Names read anywhere inside `node` (a call through a variable `f(x)` reads `f`)."""
    out: set[str] = set()
    for n in _walk(node):
        if isinstance(n, Name):
            out.add(n.name)
        elif isinstance(n, Call) and not n.qualifier:
            out.add(n.callee)
    return frozenset(out)


class Liveness:
    def __init__(self, body: list[Stmt]) -> None:
        self.after: dict[int, frozenset[str]] = {}
        self.after_head: dict[int, frozenset[str]] = {}
        self._loops: list[tuple[frozenset[str], frozenset[str]]] = []  # (after the loop, loop head)
        self.block(body, frozenset())

    def block(self, stmts: list[Stmt], out: frozenset[str]) -> frozenset[str]:
        # A deferred statement runs when the block ends, on every path: what it reads stays live throughout.
        deferred = frozenset().union(*(uses(s.stmt) for s in stmts if isinstance(s, Defer)))
        live = out | deferred
        for s in reversed(stmts):
            if isinstance(s, Return):
                self.after[id(s)] = deferred  # what runs after a `return` is the deferred code
            elif isinstance(s, (Break, Continue)) and self._loops:
                self.after[id(s)] = self._loops[-1][0 if isinstance(s, Break) else 1] | deferred
            else:
                self.after[id(s)] = live | deferred
            live = self.stmt(s, live | deferred)
        return live | deferred

    def stmt(self, s: Stmt, out: frozenset[str]) -> frozenset[str]:
        if isinstance(s, VarDecl):
            return (out - {s.name}) | uses(s.value)
        if isinstance(s, Assign):
            if s.op == "=" and isinstance(s.target, Name):
                return (out - {s.target.name}) | uses(s.value)
            return out | uses(s.target) | uses(s.value)
        if isinstance(s, (ExprStmt, Yield)):
            return out | uses(s.expr if isinstance(s, ExprStmt) else s.value)
        if isinstance(s, Return):
            return uses(s.value) if s.value is not None else frozenset()
        if isinstance(s, Break):
            return self._loops[-1][0] if self._loops else out
        if isinstance(s, Continue):
            return self._loops[-1][1] if self._loops else out
        if isinstance(s, Defer):
            return out  # counted by `block` for the whole enclosing block
        if isinstance(s, If):
            live = self.block(s.else_body, out) if s.else_body is not None else out
            for br in reversed(s.branches):  # `elif` conditions run only when the earlier ones are false
                taken = self.block(br.body, out)
                self.after_head[id(br)] = taken
                live = uses(br.cond) | taken | live
            self.after_head[id(s)] = live
            return live
        if isinstance(s, Match):
            live: frozenset[str] = frozenset()
            for arm in s.arms:
                guard = uses(arm.guard) if arm.guard is not None else frozenset()
                live |= (guard | self.block(arm.body, out)) - {b.name for b in arm.bindings} - {arm.whole}
            self.after_head[id(s)] = live
            return uses(s.scrutinee) | live
        if isinstance(s, While):
            return self._loop(s, out, uses(s.cond), frozenset())
        if isinstance(s, For):
            head = uses(s.start) | uses(s.end) | (uses(s.step) if s.step is not None else frozenset())
            return self._loop(s, out, frozenset(), frozenset({s.var}), before=head)
        if isinstance(s, ForIn):
            bound = frozenset({s.var} | ({s.index_var} if s.index_var else set()))
            # the iterable is read again by every iteration (`for x in xs` walks `xs`)
            return self._loop(s, out, uses(s.iterable), bound)
        if isinstance(s, Wrapping):
            return self.block(s.body, out)
        return out | uses(s)

    def _loop(self, s: Stmt, out: frozenset[str], cond: frozenset[str], bound: frozenset[str],
              before: frozenset[str] = frozenset()) -> frozenset[str]:
        """Live at the loop head = condition | (body | exit). Iterates until it stops growing."""
        head = cond | out
        while True:
            self._loops.append((out, head))
            body = self.block(s.body, head) - bound  # type: ignore[attr-defined]
            self._loops.pop()
            new = cond | out | body
            if new == head:
                break
            head = new
        self.after_head[id(s)] = body | out
        return head | before
