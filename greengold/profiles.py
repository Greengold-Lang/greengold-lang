"""Coding profiles: `gg check --profile safety` holds a program to the subset that safety standards ask for.

The `safety` profile is for code under DO-178C, ISO 26262, IEC 61508 and similar rules, where "the compiler accepted it" is the
start and not the end. It reports, in the program's own files (never in the standard library):

* `unsafe_code`      an `unsafe:` block (raw pointers, `asm`, `static` access, FFI) in the function;
* `panic`             an explicit `panic(...)`, `value_or_panic()`, or `unreachable` call: a way to stop the program on purpose;
* `recursion`         a function that can call itself, directly or through others;
* `heap`              a heap type (`List`, `string`, `Box`, `Shared`, `Arc`, closures `Fn`, `dyn`, the heap collections) or
                      an f-string (it builds a `string`);
* `unbounded-loop`    a `while` loop (its bound is not in its form: use `for`, or give the loop a counter and say so with
                      `@allow(unbounded_loop)`);
* `mutable-static`    a `static` variable (global mutable state);
* `complexity`        a function whose cyclomatic complexity (1 + decisions: `if`/`elif`, loops, `match` arms, `and`, `or`,
                      `?`) is over `--max-complexity` (default 15);
* `long-function`     a function with more statements than `--max-statements` (default 80).

A function can opt out of a rule with `@allow(rule)` (up to three rules in one attribute), which is itself reported by
`gg check --profile safety --list-allowed` so that a reviewer sees every exception. Run-time checks (bounds, overflow, division)
still exist in a program that passes: they stop the program, and `@panic_handler` decides what happens then.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from .ast_nodes import (
    Apply, Binary, Call, ConstDecl, For, ForIn, FuncDecl, If, Match, MethodCall, Name, Node, Try, While, walk,
)
from .diagnostics import DiagnosticBag

PACKAGE_DIR = Path(__file__).resolve().parent
RULES = ("unsafe_code", "panic", "recursion", "heap", "unbounded_loop", "mutable_static", "complexity", "long_function")
SLUG = {"unsafe_code": "profile-unsafe", "panic": "profile-panic", "recursion": "profile-recursion", "heap": "profile-heap",
        "unbounded_loop": "profile-unbounded-loop", "mutable_static": "profile-mutable-static",
        "complexity": "profile-complexity", "long_function": "profile-long-function"}

HEAP_WORDS = re.compile(r"\b(List|Box|Shared|Arc|string|dyn|HashMap|HashSet|Deque|Heap|PriorityQueue|SortedMap|SortedSet|BitSet|"
                        r"Arena|Queue|Channel)\b|Fn\(")
PANIC_CALLS = {"panic", "value_or_panic", "unreachable"}


@dataclass
class Options:
    max_complexity: int = 15
    max_statements: int = 80
    allow_rules: set[str] = field(default_factory=set)      # rules switched off for the whole run


@dataclass
class Exception_:
    """One `@allow(...)` use."""
    function: str
    rule: str
    file: str | None
    line: int


def _is_user_file(filename: str | None) -> bool:
    if not filename:
        return False
    try:
        path = Path(filename).resolve()
    except OSError:
        return False
    return PACKAGE_DIR not in path.parents


def _user_functions(program) -> list[FuncDecl]:
    out = []
    for d in program.decls:
        if isinstance(d, FuncDecl) and not getattr(d, "from_prelude", False) and d.body is not None \
                and _is_user_file(getattr(d, "filename", None)) and not d.is_test and d.inst_key is None \
                and not getattr(d, "archetype_stub", False) and not getattr(d, "from_feature_default", False):
            out.append(d)
    return out


def _allowed(fn: FuncDecl) -> set[str]:
    rules: set[str] = set()
    for a in fn.attrs:
        if a.name == "allow":
            values = getattr(a, "resolved", None) or {}
            for v in values.values():
                if isinstance(v, str) and v != "none":
                    rules.add(v)
    return rules


def allowed_exceptions(program) -> list[Exception_]:
    """Every `@allow` in the program's own files, for review."""
    out: list[Exception_] = []
    for fn in _user_functions(program):
        for a in fn.attrs:
            if a.name == "allow":
                for v in (getattr(a, "resolved", None) or {}).values():
                    if isinstance(v, str) and v != "none":
                        out.append(Exception_(fn.name if not fn.owner else f"{fn.owner}.{fn.name}", v, fn.filename, a.line))
    return out


def _complexity(fn: FuncDecl) -> int:
    n = 1
    for node in walk(fn.body):
        if isinstance(node, If) and not node.unsafe:
            n += len(node.branches)
        elif isinstance(node, (For, ForIn, While)):
            n += 1
        elif isinstance(node, Match):
            n += max(len(node.arms) - 1, 0)
        elif isinstance(node, Binary) and node.op in ("and", "or"):
            n += 1
        elif isinstance(node, Try):
            n += 1
    return n


def _statements(body) -> int:
    from .ast_nodes import Stmt
    return sum(1 for n in walk(body) if isinstance(n, Stmt))


def _calls(fn: FuncDecl, names: dict[str, FuncDecl]) -> set[str]:
    out: set[str] = set()
    for node in walk(fn.body):
        if isinstance(node, Call) and node.callee in names:
            out.add(node.callee)
        elif isinstance(node, MethodCall):
            key = f"{getattr(node, 'owner', '')}.{node.method}"
            if key in names:
                out.add(key)
    return out


def _key(fn: FuncDecl) -> str:
    return f"{fn.owner}.{fn.name}" if fn.owner else fn.name


def _cycles(funcs: list[FuncDecl]) -> set[str]:
    """Keys of the functions that lie on a call cycle."""
    names = {_key(f): f for f in funcs}
    graph = {k: _calls(f, names) for k, f in names.items()}
    on_cycle: set[str] = set()
    for start in graph:
        seen: set[str] = set()
        stack = list(graph[start])
        while stack:
            n = stack.pop()
            if n == start:
                on_cycle.add(start)
                break
            if n in seen:
                continue
            seen.add(n)
            stack.extend(graph.get(n, ()))
    return on_cycle


def check(program, diags: DiagnosticBag, opts: Options | None = None) -> int:
    """Reports the profile's findings as errors; returns how many."""
    opts = opts or Options()
    funcs = _user_functions(program)
    before = len(diags.items)
    cyc = _cycles(funcs)

    def report(fn: FuncDecl, rule: str, node: Node, message: str, hint: str) -> None:
        if rule in opts.allow_rules or rule in _allowed(fn):
            return
        diags.error(message, node.line or fn.line, node.col or fn.col, max(node.length, 1), hint,
                    filename=getattr(node, "filename", None) or fn.filename, rule=SLUG[rule])

    for fn in funcs:
        shown = _key(fn)
        reported_heap = False
        for node in walk(fn.body):
            if isinstance(node, If) and node.unsafe:
                report(fn, "unsafe_code", node, f"`unsafe:` in `{shown}`.",
                       "Use the library (`std.mmio`, `std.heapless`) that does the unsafe part, or mark the function `@allow(unsafe_code)` "
                       "and review it.")
            elif isinstance(node, Call) and node.callee in PANIC_CALLS:
                report(fn, "panic", node, f"`{node.callee}` in `{shown}` stops the program on purpose.",
                       "Return a `Result` or an `Optional` and let the caller decide.")
            elif isinstance(node, MethodCall) and node.method in PANIC_CALLS:
                report(fn, "panic", node, f"`.{node.method}()` in `{shown}` stops the program when the value is missing.",
                       "Match on the value, or use `value_or(fallback)`.")
            elif isinstance(node, While):
                report(fn, "unbounded_loop", node, f"A `while` loop in `{shown}` has no bound in its form.",
                       "Use `for i in 0..N`, or keep `while` and write `@allow(unbounded_loop)` on the function with the reason.")
            if not reported_heap:
                ty = getattr(node, "ty", None)
                if isinstance(ty, str) and (HEAP_WORDS.search(ty) or type(node).__name__ == "FormatStr"):
                    reported_heap = True
                    report(fn, "heap", node, f"`{shown}` uses the heap (`{ty}`).",
                           "Use fixed-size arrays and `std.heapless` types, or `@allow(heap)` with the reason.")
        for p in fn.params:
            pt = getattr(p, "ty", None) or (p.type_ref.name if p.type_ref is not None else "")
            if not reported_heap and isinstance(pt, str) and HEAP_WORDS.search(pt):
                reported_heap = True
                report(fn, "heap", p, f"`{shown}` takes a heap type (`{pt}`).",
                       "Use fixed-size arrays and `std.heapless` types, or `@allow(heap)` with the reason.")
        if shown in cyc:
            report(fn, "recursion", fn, f"`{shown}` can call itself.",
                   "Rewrite it with a loop and a fixed-size stack, or `@allow(recursion)` with the depth bound.")
        c = _complexity(fn)
        if c > opts.max_complexity:
            report(fn, "complexity", fn, f"`{shown}` has complexity {c} (limit {opts.max_complexity}).",
                   "Split it into smaller functions.")
        n = _statements(fn.body)
        if n > opts.max_statements:
            report(fn, "long_function", fn, f"`{shown}` has {n} statements (limit {opts.max_statements}).",
                   "Split it into smaller functions.")
    for d in program.decls:
        if isinstance(d, ConstDecl) and getattr(d, "is_static", False) and _is_user_file(getattr(d, "filename", None)):
            if "mutable_static" not in opts.allow_rules:
                diags.error(f"`static {d.name}` is global mutable state.", d.line, d.col, max(d.length, 1),
                            "Pass the state in as a parameter, or keep it in a struct owned by `main`.",
                            filename=d.filename, rule=SLUG["mutable_static"])
    return len(diags.items) - before
