"""Soundness fuzzer for the view/borrow checker.

Generates random programs that move `str` views of `string` owners through blocks, loops, lists,
calls and mutations. Each program is also run by a small model that knows exactly which view points
at freed or changed memory on the path that really executes. A program the compiler ACCEPTS while
the model says a view dangles is a soundness hole. A program it rejects although the model says it
is safe is only a false positive (reported as a count).

    python tools/fuzz_views.py [--count 5000] [--seed 1] [--out DIR]
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
fn id(a: str) -> str:
    return a

fn eat(x: consume string):
    print(x.len)

"""
NVIEWS = 3


class Gen:
    def __init__(self, rng: random.Random):
        self.r = rng
        self.n_owner = 0
        self.n_loop = 0

    def block(self, owners: list[str], loops: list[str], depth: int, local: list[str]) -> list:
        """`owners` are readable here; `local` are the ones declared in this block (may be eaten)."""
        out = []
        for _ in range(self.r.randint(1, 5)):
            out.append(self.stmt(owners, loops, depth, local))
        return out

    def stmt(self, owners, loops, depth, local):
        r = self.r
        views = [f"v{i}" for i in range(NVIEWS)]
        choices = ["new", "view", "copy", "lit", "pass", "pass2", "push", "use", "usel"]
        if owners:
            choices += ["clear", "renew", "view", "view", "pass"]
        if local:
            choices += ["eat"]
        if depth < 3:
            choices += ["if", "for", "for", "if"]
        k = r.choice(choices)
        if k == "new" or (k in ("view", "pass", "clear", "renew") and not owners):
            name = f"o{self.n_owner}"
            self.n_owner += 1
            owners.append(name)
            local.append(name)
            return ("new", name)
        v = r.choice(views)
        if k == "view":
            return ("view", v, r.choice(owners))
        if k == "copy":
            return ("copy", v, r.choice(views))
        if k == "lit":
            return ("lit", v)
        if k == "pass":
            return ("pass", v, r.choice(owners))
        if k == "pass2":
            return ("pass2", v, r.choice(views))
        if k == "push":
            return ("push", r.choice(views))
        if k == "use":
            return ("use", v)
        if k == "usel":
            return ("usel",)
        if k == "clear":
            return ("clear", r.choice(owners))
        if k == "renew":
            return ("renew", r.choice(owners))
        if k == "eat":
            o = r.choice(local)
            local.remove(o)
            owners.remove(o)
            return ("eat", o)
        if k == "if":
            cond = self.cond(loops)
            body = self.block(list(owners), loops, depth + 1, [])
            els = self.block(list(owners), loops, depth + 1, []) if r.random() < 0.5 else []
            return ("if", cond, body, els)
        if k == "for":
            name = f"i{self.n_loop}"
            self.n_loop += 1
            n = r.randint(1, 3)
            body = self.block(list(owners), loops + [name], depth + 1, [])
            return ("for", name, n, body)
        raise AssertionError(k)

    def cond(self, loops):
        if loops and self.r.random() < 0.6:
            return ("mod", self.r.choice(loops), self.r.randint(0, 1))
        return ("const", self.r.random() < 0.5)


def render(prog) -> str:
    lines = ["fn main():"]
    for i in range(NVIEWS):
        lines.append(f'    v{i} = "lit"')
    lines.append("    xs = List[str]()")
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
        elif k == "copy":
            out.append(f"{pad}{s[1]} = {s[2]}")
        elif k == "lit":
            out.append(f'{pad}{s[1]} = "lit"')
        elif k == "pass":
            out.append(f"{pad}{s[1]} = id({s[2]}.as_str())")
        elif k == "pass2":
            out.append(f"{pad}{s[1]} = id({s[2]})")
        elif k == "push":
            out.append(f"{pad}xs.push({s[1]})")
        elif k == "use":
            out.append(f"{pad}print({s[1]})")
        elif k == "usel":
            out.append(f"{pad}if xs.len > 0:")
            out.append(f"{pad}    print(xs[0])")
        elif k == "clear":
            out.append(f"{pad}{s[1]}.clear()")
        elif k == "renew":
            out.append(f'{pad}{s[1]} = string("new")')
        elif k == "eat":
            out.append(f"{pad}eat({s[1]})")
        elif k == "if":
            out.append(f"{pad}if {_cond(s[1])}:")
            out += _render_block(s[2], ind + 1) or [f"{pad}    pass"]
            if s[3]:
                out.append(f"{pad}else:")
                out += _render_block(s[3], ind + 1)
        elif k == "for":
            out.append(f"{pad}for {s[1]} in 0..{s[2]}:")
            out += _render_block(s[3], ind + 1)
    return out


def _cond(c):
    if c[0] == "const":
        return "true" if c[1] else "false"
    return f"{c[1]} % 2 == {c[2]}"


class Model:
    """Runs the program on the real path and records views used while their memory is gone."""

    def __init__(self):
        self.buf_next = 0
        self.freed: set[int] = set()
        self.version: dict[int, int] = {}
        self.owner: dict[str, int] = {}
        self.view: dict[str, tuple | None] = {f"v{i}": None for i in range(NVIEWS)}
        self.xs: list[tuple | None] = []
        self.bad: str | None = None

    def alloc(self):
        b = self.buf_next
        self.buf_next += 1
        self.version[b] = 0
        return b

    def ok(self, ref):
        return ref is None or (ref[0] not in self.freed and self.version[ref[0]] == ref[1])

    def use(self, ref, what):
        if not self.ok(ref) and self.bad is None:
            self.bad = what

    def run(self, stmts, env, scope_owners):
        for s in stmts:
            k = s[0]
            if k == "new":
                self.owner[s[1]] = self.alloc()
                scope_owners.append(s[1])
            elif k in ("view", "pass"):
                b = self.owner[s[2]]
                self.view[s[1]] = (b, self.version[b])
            elif k in ("copy", "pass2"):
                self.view[s[1]] = self.view[s[2]]
            elif k == "lit":
                self.view[s[1]] = None
            elif k == "push":
                self.xs.append(self.view[s[1]])
            elif k == "use":
                self.use(self.view[s[1]], f"print({s[1]})")
            elif k == "usel":
                if self.xs:
                    self.use(self.xs[0], "print(xs[0])")
            elif k == "clear":
                self.version[self.owner[s[1]]] += 1
            elif k == "renew":
                self.freed.add(self.owner[s[1]])
                self.owner[s[1]] = self.alloc()
            elif k == "eat":
                self.freed.add(self.owner[s[1]])
                scope_owners.remove(s[1])
            elif k == "if":
                c = s[1]
                taken = c[1] if c[0] == "const" else env[c[1]] % 2 == c[2]
                self._inner(s[2] if taken else s[3], env)
            elif k == "for":
                for i in range(s[2]):
                    self._inner(s[3], {**env, s[1]: i})

    def _inner(self, body, env):
        mine: list[str] = []
        self.run(body, env, mine)
        for o in mine:  # scope exit frees what this block still owns
            self.freed.add(self.owner[o])


def check(src: str):
    diags = DiagnosticBag()
    toks = tokenize(src, diags)
    if not diags.has_errors():
        prog = parse(toks, diags)
        if not diags.has_errors():
            check_program(prog, diags)
    return [d for d in diags.items if getattr(d, "severity", "error") == "error"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=5000)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--out", default="")
    a = ap.parse_args()
    out = Path(a.out) if a.out else None
    if out:
        out.mkdir(parents=True, exist_ok=True)
    stats = collections.Counter()
    other_codes = collections.Counter()
    holes = []
    for n in range(a.count):
        rng = random.Random(a.seed * 1_000_003 + n)
        g = Gen(rng)
        prog = g.block([], [], 0, [])
        src = render(prog)
        m = Model()
        m.run(prog, {}, [])
        errs = check(src)
        codes = {getattr(d, "code", "?") for d in errs}
        unsafe = m.bad is not None
        stats["unsafe" if unsafe else "safe"] += 1
        if errs:
            stats["rejected"] += 1
            for c in codes - {"GG0315", "GG0316"}:
                other_codes[c] += 1
                if out and other_codes[c] <= 2:
                    (out / f"other_{c}_{n}.gg").write_text(src, encoding="utf-8")
        if unsafe and not errs:
            holes.append((n, m.bad))
            if out:
                (out / f"HOLE_{n}.gg").write_text(f"# dangling use: {m.bad}\n" + src, encoding="utf-8")
        elif not unsafe and errs:
            stats["false_positive"] += 1
    print(f"programs: {a.count}  unsafe-on-path: {stats['unsafe']}  safe: {stats['safe']}")
    print(f"rejected: {stats['rejected']}  false positives (safe but rejected): {stats['false_positive']}")
    print(f"error codes other than GG0315/GG0316: {dict(other_codes) or 'none'}")
    print(f"SOUNDNESS HOLES (accepted but dangling): {len(holes)}")
    for n, why in holes[:20]:
        print(f"  program #{n}: {why}")
    return 1 if holes else 0


if __name__ == "__main__":
    sys.exit(main())
