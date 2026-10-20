"""Static checks on the generated LLVM IR, for code that must not allocate, recurse, or overflow its stack.

* `--forbid-heap`: no function reachable from an entry point (a non-internal definition) calls `malloc`,
  `realloc`, `calloc`, `free`, or the program's own `allocator` functions.
* `--forbid-recursion`: the call graph of the reachable functions has no cycle.
* `--max-stack BYTES` and `gg stack-usage`: a bound on the stack a program uses, from the sizes of every
  function's local variables (`alloca`) plus a fixed cost per call, along the deepest call chain.

The IR is looked at as text. Calls through a function pointer, a closure, or a `dyn` value cannot be followed; the
report says how many there are (`indirect`), and the stack bound does not include what they call. The sizes come
from the unoptimized IR, where every local has its own slot, so they are an upper bound for an optimized build.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

HEAP_CALLS = {"malloc", "calloc", "realloc", "free", "aligned_alloc", "posix_memalign", "_aligned_malloc",
              "_aligned_free", "strdup",
              "gg_rt_alloc", "gg_rt_realloc", "gg_rt_free"}  # the last three are the program's own heap runtime

_DEFINE = re.compile(r'^define\s+(?P<head>[^@]*?)@(?P<name>"[^"]+"|[\w.$]+)\(')
_CALL = re.compile(r'\bcall\b[^@%\n]*?(?:\([^)]*\)\s*)?(?P<callee>@"[^"]+"|@[\w.$]+|%"[^"]+"|%[\w.$]+)\(')
_ALLOCA = re.compile(r'=\s*alloca\s+(?P<ty>.+?)(?:,\s*(?:i\d+\s+(?P<n>\d+)|align\s+\d+).*)?$')
_NAMED_TYPE = re.compile(r'^(?P<name>%"[^"]+"|%[\w.$]+)\s*=\s*type\s+(?P<body>.+)$')
_TRIPLE_PTR32 = ("thumb", "arm", "i386", "i686", "riscv32", "wasm32", "mips")


@dataclass
class FuncInfo:
    name: str
    external: bool
    calls: set[str] = field(default_factory=set)
    indirect: int = 0
    alloca_bytes: int = 0


def _unquote(sym: str) -> str:
    sym = sym.lstrip("@")
    return sym[1:-1] if sym.startswith('"') else sym


def _split_top(text: str) -> list[str]:
    """Splits `a, b, c` at top-level commas (not inside brackets, braces, or angle brackets)."""
    parts, depth, cur = [], 0, []
    for ch in text:
        if ch in "[{<(":
            depth += 1
        elif ch in "]}>)":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append("".join(cur).strip())
            cur = []
        else:
            cur.append(ch)
    if "".join(cur).strip():
        parts.append("".join(cur).strip())
    return parts


class _Types:
    def __init__(self, named: dict[str, str], ptr_bytes: int) -> None:
        self.named = named
        self.ptr = ptr_bytes
        self._cache: dict[str, tuple[int, int]] = {}

    def size_align(self, ty: str) -> tuple[int, int]:
        ty = ty.strip()
        hit = self._cache.get(ty)
        if hit is not None:
            return hit
        self._cache[ty] = (0, 1)  # guards a self-referential named type
        out = self._compute(ty)
        self._cache[ty] = out
        return out

    def _compute(self, ty: str) -> tuple[int, int]:
        if ty.endswith("*") or ty == "ptr" or ty.startswith("ptr "):
            return self.ptr, self.ptr
        m = re.fullmatch(r"i(\d+)", ty)
        if m:
            bits = int(m.group(1))
            size = (bits + 7) // 8
            for p in (1, 2, 4, 8, 16, 32):
                if p >= size:
                    size = p
                    break
            return size, min(size, 16)
        if ty == "float":
            return 4, 4
        if ty == "double":
            return 8, 8
        if ty == "void":
            return 0, 1
        if ty.startswith("["):
            m = re.fullmatch(r"\[(\d+)\s*x\s*(.+)\]", ty)
            if m:
                s, a = self.size_align(m.group(2))
                return int(m.group(1)) * s, a
        if ty.startswith("<"):
            m = re.fullmatch(r"<(\d+)\s*x\s*(.+)>", ty)
            if m:
                s, a = self.size_align(m.group(2))
                total = int(m.group(1)) * s
                return total, max(a, min(total, 32))
        if ty.startswith("{") or ty.startswith("<{"):
            packed = ty.startswith("<{")
            inner = ty[2:-2] if packed else ty[1:-1]
            off, top = 0, 1
            for f in _split_top(inner):
                s, a = self.size_align(f)
                if packed:
                    a = 1
                off = (off + a - 1) // a * a + s
                top = max(top, a)
            return (off + top - 1) // top * top, top
        if ty in self.named:
            return self.size_align(self.named[ty])
        return self.ptr, self.ptr  # unknown: a pointer-sized guess


def parse_ir(ir_text: str, triple: str = "") -> dict[str, FuncInfo]:
    """Functions of an IR module: who calls whom, and how many bytes of locals each has."""
    ptr_bytes = 4 if triple.startswith(_TRIPLE_PTR32) else 8
    m = re.search(r'target datalayout = "([^"]*)"', ir_text)
    if m:
        pm = re.search(r"(?:^|-)p(?:\d+)?:(\d+):", m.group(1))
        if pm:
            ptr_bytes = int(pm.group(1)) // 8
    named: dict[str, str] = {}
    for line in ir_text.splitlines():
        nm = _NAMED_TYPE.match(line)
        if nm:
            named[nm.group("name")] = nm.group("body").strip()
    types = _Types(named, ptr_bytes)
    funcs: dict[str, FuncInfo] = {}
    cur: FuncInfo | None = None
    for line in ir_text.splitlines():
        if line.startswith("define "):
            dm = _DEFINE.match(line)
            if dm is None:
                cur = None
                continue
            head = dm.group("head")
            cur = FuncInfo(_unquote(dm.group("name")), external=not head.startswith(("internal", "private")))
            funcs[cur.name] = cur
            continue
        if cur is None:
            continue
        if line.startswith("}"):
            cur = None
            continue
        if "alloca" in line:
            am = _ALLOCA.search(line)
            if am:
                s, a = types.size_align(am.group("ty"))
                count = int(am.group("n")) if am.group("n") else 1
                cur.alloca_bytes += (s * count + 7) // 8 * 8
        if " call " in line or line.lstrip().startswith("call "):
            cm = _CALL.search(line)
            if cm is None:
                continue
            callee = cm.group("callee")
            if callee.startswith("@"):
                cur.calls.add(_unquote(callee))
            else:
                cur.indirect += 1
    return funcs


def reachable(funcs: dict[str, FuncInfo], roots: list[str] | None = None) -> set[str]:
    start = roots if roots is not None else [n for n, f in funcs.items() if f.external]
    seen: set[str] = set()
    stack = list(start)
    while stack:
        n = stack.pop()
        if n in seen or n not in funcs:
            continue
        seen.add(n)
        stack.extend(funcs[n].calls)
    return seen


def _chain(names: list[str]) -> str:
    out: list[str] = []
    for n in names:
        if not out or out[-1] != _shown(n):
            out.append(_shown(n))
    return " -> ".join(out)


def _shown(name: str) -> str:
    """`gg_fs_read_text` -> `fs.read_text` (best effort); a runtime or exported name is left alone."""
    if name.startswith("gg_"):
        return name[3:]
    return name


def _path_to(funcs: dict[str, FuncInfo], target: str, roots: list[str]) -> list[str]:
    """Shortest call chain from an entry point to `target`."""
    prev: dict[str, str | None] = {r: None for r in roots if r in funcs}
    queue = list(prev)
    while queue:
        n = queue.pop(0)
        if n == target:
            break
        for c in sorted(funcs[n].calls):
            if c in funcs and c not in prev:
                prev[c] = n
                queue.append(c)
    chain: list[str] = []
    cur: str | None = target if target in prev else None
    while cur is not None:
        chain.append(cur)
        cur = prev[cur]
    return list(reversed(chain))


def heap_users(funcs: dict[str, FuncInfo], allocator_symbols: set[str] = frozenset()) -> list[list[str]]:
    """Call chains (entry point first) that end in a heap call."""
    roots = [n for n, f in funcs.items() if f.external]
    live = reachable(funcs, roots)
    bad = HEAP_CALLS | set(allocator_symbols)
    out: list[list[str]] = []
    for name in sorted(live):
        if name in bad:
            continue  # the heap runtime calling libc: its caller is the one to report
        hits = sorted(funcs[name].calls & bad)
        if hits:
            out.append(_path_to(funcs, name, roots) + [hits[0]])
    return out


def recursion_cycles(funcs: dict[str, FuncInfo]) -> list[list[str]]:
    """Strongly connected groups (and self-calls) among the functions reachable from an entry point."""
    live = reachable(funcs)
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    on: set[str] = set()
    stack: list[str] = []
    out: list[list[str]] = []
    counter = [0]

    def visit(v: str) -> None:
        # iterative Tarjan to survive deep call graphs
        work = [(v, iter(sorted(funcs[v].calls & live)))]
        index[v] = low[v] = counter[0]
        counter[0] += 1
        stack.append(v)
        on.add(v)
        while work:
            node, it = work[-1]
            advanced = False
            for w in it:
                if w not in index:
                    index[w] = low[w] = counter[0]
                    counter[0] += 1
                    stack.append(w)
                    on.add(w)
                    work.append((w, iter(sorted(funcs[w].calls & live))))
                    advanced = True
                    break
                if w in on:
                    low[node] = min(low[node], index[w])
            if advanced:
                continue
            work.pop()
            if work:
                parent = work[-1][0]
                low[parent] = min(low[parent], low[node])
            if low[node] == index[node]:
                comp = []
                while True:
                    w = stack.pop()
                    on.discard(w)
                    comp.append(w)
                    if w == node:
                        break
                if len(comp) > 1 or node in funcs[node].calls:
                    out.append(sorted(comp))

    for v in sorted(live):
        if v not in index:
            visit(v)
    return out


@dataclass
class StackReport:
    worst: int
    chain: list[str]
    per_function: dict[str, int]
    indirect: int
    recursive: bool


def stack_usage(funcs: dict[str, FuncInfo], call_overhead: int = 32) -> StackReport:
    """Bytes of stack on the deepest call chain: locals of each function plus `call_overhead` for the return address
    and saved registers. With recursion in the graph the chain has no bound and `recursive` is true."""
    live = reachable(funcs)
    cycles = recursion_cycles(funcs)
    per = {n: funcs[n].alloca_bytes + call_overhead for n in live}
    indirect = sum(funcs[n].indirect for n in live)
    if cycles:
        return StackReport(0, [], per, indirect, True)
    memo: dict[str, tuple[int, list[str]]] = {}

    def depth(n: str) -> tuple[int, list[str]]:
        if n in memo:
            return memo[n]
        best, chain = 0, []
        for c in funcs[n].calls & live:
            d, ch = depth(c)
            if d > best:
                best, chain = d, ch
        memo[n] = (per[n] + best, [n] + chain)
        return memo[n]

    import sys
    sys.setrecursionlimit(max(sys.getrecursionlimit(), 10000))
    worst, chain = 0, []
    for n in sorted(n for n in live if funcs[n].external):
        d, ch = depth(n)
        if d > worst:
            worst, chain = d, ch
    return StackReport(worst, chain, per, indirect, False)


def check_limits(ir_text: str, triple: str, *, forbid_heap: bool, forbid_recursion: bool, max_stack: int | None,
                 allocator_symbols: set[str] = frozenset()) -> list[str]:
    """Error messages for the limits that the program breaks (empty: all hold)."""
    funcs = parse_ir(ir_text, triple)
    errors: list[str] = []
    if forbid_heap:
        for chain in heap_users(funcs, allocator_symbols):
            shown = _chain(chain)
            errors.append(f"--forbid-heap: the program allocates: {shown}")
    if forbid_recursion:
        for comp in recursion_cycles(funcs):
            errors.append("--forbid-recursion: recursive call cycle: " + " <-> ".join(_shown(c) for c in comp))
    if max_stack is not None:
        rep = stack_usage(funcs)
        if rep.recursive:
            errors.append("--max-stack: the stack cannot be bounded because the program recurses")
        elif rep.worst > max_stack:
            errors.append(f"--max-stack: the deepest call chain needs up to {rep.worst} bytes, over the limit of "
                          f"{max_stack}: " + _chain(rep.chain))
    return errors
