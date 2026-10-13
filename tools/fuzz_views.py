"""Soundness fuzzer for the view/borrow checker.

Generates random programs that move `str` views of `string` owners through blocks, loops (`for`, `while`,
`break`, `continue`), early `return`, two lists, a struct field, an `Optional[str]`, and calls (`id`, `pick`,
`keep`). Every branch condition is opaque to the compiler. A small model runs the program on EVERY path of
those conditions and records whether a view points at freed or changed memory when it is used.

  * A program the compiler ACCEPTS although some path uses a dangling view is a soundness HOLE.
  * A program it REJECTS although no path does is a false positive (a precision problem, counted and
    optionally saved with --keep-fp).

    python tools/fuzz_views.py [--count 5000] [--seed 1] [--out DIR] [--keep-fp N] [--minimize]
"""
from __future__ import annotations

import argparse
import collections
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from greengold.diagnostics import DiagnosticBag  # noqa: E402
from greengold.lexer import tokenize  # noqa: E402
from greengold.parser import parse  # noqa: E402
from greengold.typecheck import check_program  # noqa: E402

HEADER = """\
struct W:
    name: str

fn id(a: str) -> str:
    return a

fn pick(a: str, b: str) -> str:
    return a

fn keep(out: lend List[str], s: str):
    out.push(s)

fn flip(k: usize) -> bool:
    return k % 2 == 0

fn eat(x: consume string):
    print(x.len)

"""
NVIEWS = 3
VIEWS = [f"v{i}" for i in range(NVIEWS)]

# statement -> relative weight (statements that need an owner are dropped when none is in scope)
SIMPLE = {
    "new": 3, "view": 6, "copy": 2, "lit": 2, "pass": 3, "pass2": 2, "pick": 2, "pick2": 2, "slice": 2,
    "push": 2, "pusho": 2, "keep": 2, "keepo": 2, "usel": 2, "fromlist": 2, "split": 2, "usey": 2,
    "setf": 2, "setfo": 2, "getf": 2, "usef": 2, "setopt": 2, "setoptn": 1, "useopt": 2,
    "use": 4, "clear": 3, "renew": 3,
}
NEEDS_OWNER = {"view", "pass", "pick", "pick2", "slice", "pusho", "keepo", "split", "setfo", "clear", "renew"}


class Gen:
    def __init__(self, rng: random.Random):
        self.r = rng
        self.n_owner = 0
        self.n_loop = 0

    def block(self, owners: list[str], depth: int, local: list[str], in_loop: bool = False,
              can_ret: bool = True) -> list:
        """`owners` are readable here; `local` are the ones declared in this block (may be eaten)."""
        out = [self.stmt(owners, depth, local, in_loop, can_ret) for _ in range(self.r.randint(1, 5))]
        # `break`, `continue` and `return` end a block
        if in_loop and self.r.random() < 0.12:
            out.append((self.r.choice(["break", "continue"]),))
        elif depth > 0 and can_ret and self.r.random() < 0.05:
            out.append(("ret",))
        return out

    def stmt(self, owners, depth, local, in_loop, can_ret):
        r = self.r
        names, weights = zip(*SIMPLE.items())
        names, weights = list(names), list(weights)
        if not owners:
            keep = [i for i, n in enumerate(names) if n not in NEEDS_OWNER]
            names, weights = [names[i] for i in keep], [weights[i] for i in keep]
        if local:
            names.append("eat")
            weights.append(2)
        if depth < 3:
            names += ["if", "for", "while"]
            weights += [4, 3, 2]
        k = r.choices(names, weights)[0]
        v, v2, v3 = (r.choice(VIEWS) for _ in range(3))
        if k == "new":
            name = f"o{self.n_owner}"
            self.n_owner += 1
            owners.append(name)
            local.append(name)
            return ("new", name)
        if k in ("view", "pass", "slice"):
            return (k, v, r.choice(owners))
        if k in ("copy", "pass2"):
            return (k, v, v2)
        if k == "pick":
            return ("pick", v, v2, v3)
        if k == "pick2":  # pick(view, o.as_str()): the call returns its first argument
            return ("pick2", v, v2, r.choice(owners))
        if k in ("lit", "use", "push", "keep", "fromlist", "getf", "setf", "setopt"):
            return (k, v)
        if k in ("pusho", "keepo", "split", "setfo", "clear", "renew"):
            return (k, r.choice(owners))
        if k in ("usel", "usey", "usef", "useopt", "setoptn"):
            return (k,)
        if k == "eat":
            o = r.choice(local)
            local.remove(o)
            owners.remove(o)
            return ("eat", o)
        if k == "if":
            body = self.block(list(owners), depth + 1, [], in_loop, can_ret)
            els = self.block(list(owners), depth + 1, [], in_loop, can_ret) if r.random() < 0.5 else []
            return ("if", body, els)
        if k == "for":
            name = f"i{self.n_loop}"
            self.n_loop += 1
            return ("for", name, r.randint(2, 3), self.block(list(owners), depth + 1, [], True, can_ret))
        if k == "while":
            return ("while", self.block(list(owners), depth + 1, [], True, can_ret))
        raise AssertionError(k)


def render(prog) -> str:
    lines = ["fn main():"]
    lines += [f'    {v} = "lit"' for v in VIEWS]
    lines += ["    xs = List[str]()", "    ys = List[str]()", '    w = W{ name: "lit" }',
              "    op: Optional[str] = None"]
    lines += _render_block(prog, 1)
    lines.append("    print(xs.len)")
    return HEADER + "\n".join(lines) + "\n"


def _render_block(stmts, ind):
    pad = "    " * ind
    out = []
    for s in stmts:
        k = s[0]
        if k == "new":
            out.append(f'{pad}{s[1]} = string("data")')
        elif k == "view":
            out.append(f"{pad}{s[1]} = {s[2]}.as_str()")
        elif k in ("copy",):
            out.append(f"{pad}{s[1]} = {s[2]}")
        elif k == "lit":
            out.append(f'{pad}{s[1]} = "lit"')
        elif k == "pass":
            out.append(f"{pad}{s[1]} = id({s[2]}.as_str())")
        elif k == "pass2":
            out.append(f"{pad}{s[1]} = id({s[2]})")
        elif k == "pick":
            out.append(f"{pad}{s[1]} = pick({s[2]}, {s[3]})")
        elif k == "pick2":
            out.append(f"{pad}{s[1]} = pick({s[2]}, {s[3]}.as_str())")
        elif k == "slice":
            out.append(f"{pad}{s[1]} = {s[2]}[0..1]")
        elif k == "push":
            out.append(f"{pad}xs.push({s[1]})")
        elif k == "pusho":
            out.append(f"{pad}xs.push({s[1]}.as_str())")
        elif k == "keep":
            out.append(f"{pad}keep(xs, {s[1]})")
        elif k == "keepo":
            out.append(f"{pad}keep(xs, {s[1]}.as_str())")
        elif k == "usel":
            out += [f"{pad}if xs.len > 0:", f"{pad}    print(xs[0])"]
        elif k == "fromlist":
            out += [f"{pad}if xs.len > 0:", f"{pad}    {s[1]} = xs[0]"]
        elif k == "split":
            out.append(f'{pad}ys = {s[1]}.split(" ")')
        elif k == "usey":
            out += [f"{pad}if ys.len > 0:", f"{pad}    print(ys[0])"]
        elif k == "setf":
            out.append(f"{pad}w.name = {s[1]}")
        elif k == "setfo":
            out.append(f"{pad}w.name = {s[1]}.as_str()")
        elif k == "getf":
            out.append(f"{pad}{s[1]} = w.name")
        elif k == "usef":
            out.append(f"{pad}print(w.name)")
        elif k == "setopt":
            out.append(f"{pad}op = Valid({s[1]})")
        elif k == "setoptn":
            out.append(f"{pad}op = None")
        elif k == "useopt":
            out += [f"{pad}match op:", f"{pad}    Valid(x):", f"{pad}        print(x)", f"{pad}    None:",
                    f'{pad}        print("n")']
        elif k == "use":
            out.append(f"{pad}print({s[1]})")
        elif k == "clear":
            out.append(f"{pad}{s[1]}.clear()")
        elif k == "renew":
            out.append(f'{pad}{s[1]} = string("new")')
        elif k == "eat":
            out.append(f"{pad}eat({s[1]})")
        elif k in ("break", "continue"):
            out.append(f"{pad}{k}")
        elif k == "ret":
            out.append(f"{pad}return")
        elif k == "if":
            out.append(f"{pad}if flip(xs.len):")
            out += _render_block(s[1], ind + 1) or [f"{pad}    pass"]
            if s[2]:
                out.append(f"{pad}else:")
                out += _render_block(s[2], ind + 1)
        elif k == "for":
            out.append(f"{pad}for {s[1]} in 0..{s[2]}:")
            out += _render_block(s[3], ind + 1)
        elif k == "while":
            out.append(f"{pad}while flip(xs.len):")
            out += _render_block(s[1], ind + 1)
        else:
            raise AssertionError(k)
    return out


class _Break(Exception):
    pass


class _Continue(Exception):
    pass


class _Return(Exception):
    pass


class Model:
    """Runs the program along one path and records the first use of a view whose memory is gone.

    A view is `(buffer, version)`; `clear`ing or reassigning the owner invalidates it, and so does the
    end of the owner's block. Copying a dangling view counts as a use (Rust rejects that too), and so does
    any use of a list that holds one.
    """

    def __init__(self, prefix=()):
        self.prefix = list(prefix)
        self.taken: list[bool] = []  # every branch decision of this run, in order
        self.buf_next = 0
        self.freed: set[int] = set()
        self.version: dict[int, int] = {}
        self.owner: dict[str, int] = {}
        self.view: dict[str, tuple | None] = {v: None for v in VIEWS}
        self.xs: list[tuple | None] = []
        self.ys: list[tuple | None] = []
        self.fld: tuple | None = None
        self.opt: tuple | None = None
        self.bad: str | None = None
        self.returned = False

    def alloc(self):
        b = self.buf_next
        self.buf_next += 1
        self.version[b] = 0
        return b

    def ref(self, o):
        b = self.owner[o]
        return (b, self.version[b])

    def ok(self, ref):
        return ref is None or (ref[0] not in self.freed and self.version[ref[0]] == ref[1])

    def use(self, ref, what):
        if not self.ok(ref) and self.bad is None:
            self.bad = what

    def use_list(self, lst, what):
        for ref in lst:
            self.use(ref, what)

    def decide(self):
        i = len(self.taken)
        d = self.prefix[i] if i < len(self.prefix) else False
        self.taken.append(d)
        return d

    def run(self, stmts, scope_owners):
        for s in stmts:
            k = s[0]
            V = self.view
            if k == "new":
                self.owner[s[1]] = self.alloc()
                scope_owners.append(s[1])
            elif k in ("view", "pass", "slice"):
                V[s[1]] = self.ref(s[2])
            elif k in ("copy", "pass2", "pick"):  # `pick(a, b)` returns `a`
                self.use(V[s[2]], f"{s[1]} = {s[2]}")
                if k == "pick":
                    self.use(V[s[3]], f"{s[1]} = pick(.., {s[3]})")
                V[s[1]] = V[s[2]]
            elif k == "pick2":
                self.use(V[s[2]], f"{s[1]} = pick({s[2]}, ..)")
                V[s[1]] = V[s[2]]
            elif k == "lit":
                V[s[1]] = None
            elif k in ("push", "keep"):
                self.use_list(self.xs, "xs.push")
                self.use(V[s[1]], f"xs.push({s[1]})")
                self.xs.append(V[s[1]])
            elif k in ("pusho", "keepo"):
                self.use_list(self.xs, "xs.push")
                self.xs.append(self.ref(s[1]))
            elif k == "usel":
                self.use_list(self.xs, "xs.len")
                if self.xs:
                    self.use(self.xs[0], "print(xs[0])")
            elif k == "fromlist":
                self.use_list(self.xs, "xs.len")
                if self.xs:
                    V[s[1]] = self.xs[0]
            elif k == "split":
                self.ys = [self.ref(s[1])]
            elif k == "usey":
                self.use_list(self.ys, "ys.len")
            elif k == "setf":
                self.use(V[s[1]], f"w.name = {s[1]}")
                self.fld = V[s[1]]
            elif k == "setfo":
                self.fld = self.ref(s[1])
            elif k == "getf":
                self.use(self.fld, f"{s[1]} = w.name")
                V[s[1]] = self.fld
            elif k == "usef":
                self.use(self.fld, "print(w.name)")
            elif k == "setopt":
                self.use(V[s[1]], f"op = Valid({s[1]})")
                self.opt = V[s[1]]
            elif k == "setoptn":
                self.opt = None
            elif k == "useopt":
                self.use(self.opt, "match op")
            elif k == "use":
                self.use(V[s[1]], f"print({s[1]})")
            elif k == "clear":
                self.version[self.owner[s[1]]] += 1
            elif k == "renew":
                self.freed.add(self.owner[s[1]])
                self.owner[s[1]] = self.alloc()
            elif k == "eat":
                self.freed.add(self.owner[s[1]])
                scope_owners.remove(s[1])
            elif k == "break":
                raise _Break
            elif k == "continue":
                raise _Continue
            elif k == "ret":
                raise _Return
            elif k == "if":
                self.use_list(self.xs, "flip(xs.len)")
                self._inner(s[1] if self.decide() else s[2])
            elif k == "for":
                for _ in range(s[2]):
                    try:
                        self._inner(s[3])
                    except _Continue:
                        continue
                    except _Break:
                        break
            elif k == "while":
                for it in range(3):
                    self.use_list(self.xs, "flip(xs.len)")
                    if it == 2 or not self.decide():
                        break
                    try:
                        self._inner(s[1])
                    except _Continue:
                        continue
                    except _Break:
                        break

    def _inner(self, body):
        mine: list[str] = []
        try:
            self.run(body, mine)
        finally:
            for o in mine:  # the block's own variables are gone when it ends, however it ends
                self.freed.add(self.owner[o])


def unsafe_path(prog, cap: int = 400):
    """Tries every combination of branch decisions. Returns (reason or None, complete)."""
    todo = [[]]
    runs = 0
    while todo:
        if runs >= cap:
            return None, False
        prefix = todo.pop()
        m = Model(prefix)
        try:
            m.run(prog, [])
        except _Return:
            m.returned = True
        except (_Break, _Continue):
            raise AssertionError("break/continue outside a loop")
        if not m.returned:
            m.use_list(m.xs, "print(xs.len)")  # the last line of main reads the list
        runs += 1
        if m.bad is not None:
            return m.bad, True
        for j in range(len(prefix), len(m.taken)):
            todo.append(m.taken[:j] + [True])
    return None, True


def check(src: str):
    diags = DiagnosticBag()
    toks = tokenize(src, diags)
    if not diags.has_errors():
        prog = parse(toks, diags)
        if not diags.has_errors():
            check_program(prog, diags)
    return [d for d in diags.items if getattr(d, "severity", "error") == "error"]


BORROW_CODES = ("GG0315", "GG0316")


def borrow_errors_only(errs) -> bool:
    return bool(errs) and all(getattr(d, "code", "") in BORROW_CODES for d in errs)


def _variants(stmts):
    """Smaller programs: drop a statement, replace a block by its body, lower a loop count."""
    for i in range(len(stmts)):
        yield stmts[:i] + stmts[i + 1:]
        s = stmts[i]
        pre, post = stmts[:i], stmts[i + 1:]
        if s[0] == "if":
            for b in _variants(s[1]):
                yield pre + [("if", b, s[2])] + post
            for b in _variants(s[2]):
                yield pre + [("if", s[1], b)] + post
            yield pre + list(s[1]) + post
            yield pre + list(s[2]) + post
        elif s[0] == "for":
            for b in _variants(s[3]):
                yield pre + [("for", s[1], s[2], b)] + post
            if s[2] > 2:
                yield pre + [("for", s[1], s[2] - 1, s[3])] + post
            yield pre + list(s[3]) + post
        elif s[0] == "while":
            for b in _variants(s[1]):
                yield pre + [("while", b)] + post
            yield pre + list(s[1]) + post


def minimize(prog, still):
    """Greedy shrinking: keeps any smaller program for which `still(prog)` holds."""
    changed = True
    while changed:
        changed = False
        for v in _variants(prog):
            try:
                ok = still(v)
            except Exception:  # a removed declaration makes the model or the program invalid
                ok = False
            if ok:
                prog, changed = v, True
                break
    return prog


def is_hole(prog) -> bool:
    bad, _ = unsafe_path(prog)
    return bad is not None and not check(render(prog))


def is_false_positive(prog) -> bool:
    bad, complete = unsafe_path(prog)
    return bad is None and complete and borrow_errors_only(check(render(prog)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=5000)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--out", default="", help="write holes (and other findings) here")
    ap.add_argument("--keep-fp", type=int, default=0, help="also write this many false-positive programs to --out")
    ap.add_argument("--minimize", action="store_true", help="shrink every saved program")
    a = ap.parse_args()
    out = Path(a.out) if a.out else None
    if out:
        out.mkdir(parents=True, exist_ok=True)
    stats = collections.Counter()
    other_codes = collections.Counter()
    holes = []
    for n in range(a.count):
        rng = random.Random(a.seed * 1_000_003 + n)
        prog = Gen(rng).block([], 0, [])
        src = render(prog)
        bad, complete = unsafe_path(prog)
        errs = check(src)
        codes = {getattr(d, "code", "?") for d in errs}
        unsafe = bad is not None
        if not unsafe and not complete:
            stats["skipped_incomplete"] += 1
            continue
        stats["unsafe" if unsafe else "safe"] += 1
        if errs:
            stats["rejected"] += 1
            for c in codes - set(BORROW_CODES):  # a generator bug, not a finding
                other_codes[c] += 1
                if out and other_codes[c] <= 2:
                    (out / f"other_{c}_{n}.gg").write_text(src, encoding="utf-8")
        if unsafe and not errs:
            holes.append((n, bad))
            if out:
                shown = minimize(prog, is_hole) if a.minimize else prog
                (out / f"HOLE_{n}.gg").write_text(f"# dangling use: {bad}\n" + render(shown), encoding="utf-8")
        elif not unsafe and errs:
            stats["false_positive"] += 1
            if out and stats["false_positive"] <= a.keep_fp:
                shown = minimize(prog, is_false_positive) if a.minimize else prog
                (out / f"FP_{n}.gg").write_text(render(shown), encoding="utf-8")
    print(f"programs: {a.count}  unsafe-on-some-path: {stats['unsafe']}  safe-on-every-path: {stats['safe']}  "
          f"(skipped, too many paths: {stats['skipped_incomplete']})")
    print(f"rejected: {stats['rejected']}  false positives (safe but rejected): {stats['false_positive']}")
    print(f"error codes other than GG0315/GG0316: {dict(other_codes) or 'none'}")
    print(f"SOUNDNESS HOLES (accepted but dangling): {len(holes)}")
    for n, why in holes[:20]:
        print(f"  program #{n}: {why}")
    return 1 if holes else 0


if __name__ == "__main__":
    sys.exit(main())
