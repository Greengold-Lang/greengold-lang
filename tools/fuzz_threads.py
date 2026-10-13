"""Thread-race fuzzer: programs whose threads really overlap, checked by the memory-safety oracle.

Every program shares state between 2-4 threads through the ways the language allows (`Arc[Locked[T]]`,
`Arc[Queue[T]]`, `Atomic`, read-only `Arc[T]`, values moved into a thread, results handed back through a
queue) and then prints totals that do not depend on the order the threads ran in. A program the compiler
accepts is built with the oracle allocator (`safety_oracle.py`) and run several times with a leaking and a
poisoning heap: a difference between runs or modes (a race on the data or a read of freed memory), a double
free, a crash, or a non-zero live count means a program passed the checker that is not thread safe.

    python tools/fuzz_threads.py --show 3
    python tools/fuzz_threads.py --count 300 --jobs 6 --out findings/
"""
from __future__ import annotations

import argparse
import random
import sys
import tempfile
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

import safety_oracle as O  # noqa: E402

HEADER = """import std.thread { Thread, Locked, Queue, Atomic, AtomicI64 }

struct Item:
    name: string
    n: i32

struct Cfg:
    label: string
    vals: List[i32]

enum Msg:
    Text(string)
    Num(i32)
    Pair(string, i32)

"""

# shared resources: name, type, constructor, per-thread parameter
RES = {
    "ls": ("Arc[Locked[List[string]]]", "Arc[Locked[List[string]]](Locked[List[string]].new(List[string]()))"),
    "st": ("Arc[Locked[string]]", "Arc[Locked[string]](Locked[string].new(string.new()))"),
    "li": ("Arc[Locked[List[Item]]]", "Arc[Locked[List[Item]]](Locked[List[Item]].new(List[Item]()))"),
    "ms": ("Arc[Locked[Optional[string]]]", "Arc[Locked[Optional[string]]](Locked[Optional[string]].new(None))"),
    "bx": ("Arc[Locked[Box[Cfg]]]",
           'Arc[Locked[Box[Cfg]]](Locked[Box[Cfg]].new(Box[Cfg](Cfg{ label: string.from("c"), vals: List[i32]() })))'),
    "q": ("Arc[Queue[string]]", "Arc[Queue[string]](Queue[string].new())"),
    "qm": ("Arc[Queue[Msg]]", "Arc[Queue[Msg]](Queue[Msg].new())"),
    "qi": ("Arc[Queue[Item]]", "Arc[Queue[Item]](Queue[Item].new())"),
    "at": ("Arc[Atomic[i64]]", "Arc[Atomic[i64]](Atomic[i64].new(0))"),
    "ai": ("Arc[AtomicI64]", "Arc[AtomicI64](AtomicI64.new(0))"),
    "ro": ("Arc[Cfg]", 'Arc[Cfg](Cfg{ label: string.from("shared"), vals: three() })'),
    "rs": ("Arc[string]", 'Arc[string](string.from("read only text"))'),
    "rl": ("Arc[List[string]]", 'Arc[List[string]](two())'),
}

# operations on a resource inside a worker. `$i` is the loop variable
OPS = {
    "ls": [
        'if true:\n    g = r.value.lock()\n    g.value().push(f"w{i}")',
        "if true:\n    g = r.value.lock()\n    g.value().push(string.from(\"x\"))\n    k = g.value().len\n    print_nothing(k)",
        "n = r.value.get().len",
        "r.value.replace(List[string]())",
        'if true:\n    g = r.value.lock()\n    if g.value().len > 0:\n        s = g.value()[0].as_str()\n        print_nothing(s.len)',
        'r.value.set(two())',
    ],
    "st": [
        'x = r.value.get()\nx.append_str("ab")\nr.value.set(x)',
        "r.value.set(string.from(\"zz\"))",
        "x = r.value.get()",
        "x = r.value.replace(string.from(\"yy\"))",
        "if true:\n    g = r.value.lock()\n    v = g.value().as_str()\n    print_nothing(v.len)",
    ],
    "li": [
        'if true:\n    g = r.value.lock()\n    g.value().push(Item{ name: string.from("i"), n: i })',
        "if true:\n    g = r.value.lock()\n    k = g.value().len\n    print_nothing(usize(k))",
        "n = r.value.get().len",
        "if true:\n    g = r.value.lock()\n    if g.value().len > 2:\n        g.value().pop()",
    ],
    "ms": [
        'r.value.set(Valid(string.from("m")))',
        "o = r.value.replace(None)",
        "o = r.value.get()",
        'if true:\n    g = r.value.lock()\n    g.value() = Valid(string.from("n"))',
    ],
    "bx": [
        "c = r.value.get()\nc.value.vals.push(i)\nr.value.set(c)",
        "c = r.value.get()\nc.value.label.append_str(\"b\")\nr.value.set(c)",
        "c = r.value.get()",
        'r.value.set(Box[Cfg](Cfg{ label: string.from("n"), vals: List[i32]() }))',
    ],
    "q": [
        'r.value.send(f"s{i}")',
    ],
    "qm": [
        "r.value.send(Msg.Num(i))",
        'r.value.send(Msg.Text(string.from("t")))',
        'r.value.send(Msg.Pair(string.from("p"), i))',
    ],
    "qi": [
        'r.value.send(Item{ name: string.from("q"), n: i })',
    ],
    "at": [
        "r.value.fetch_add(1)",
        "r.value.fetch_sub(1)",
        "x = r.value.load()",
        "r.value.swap(5)",
        "r.value.store(r.value.load())",
    ],
    "ai": [
        "r.value.fetch_and_add(2)",
        "x = r.value.load()",
    ],
    "ro": [
        "x = r.value.label.clone()",
        "n = r.value.vals.len",
        "v = r.value.label.as_str()\nprint_nothing(v.len)",
        "t = r.value.vals[0] + r.value.vals[1]",
    ],
    "rs": [
        "x = r.value.clone()",
        "v = r.value.as_str()\nprint_nothing(v.len)",
        "y = r.clone()",
    ],
    "rl": [
        "n = r.value.len",
        "y = r.clone()",
    ],
}

# counted effects: (resource, op index) -> what a worker adds to the total, so the totals can be printed
COUNT = {
    ("ls", 0): ("ls_push", 1), ("ls", 1): ("ls_push", 1),
    ("li", 0): ("li_push", 1),
    ("q", 0): ("q_sent", 1), ("qm", 0): ("qm_sent", 1), ("qm", 1): ("qm_sent", 1), ("qm", 2): ("qm_sent", 1),
    ("qi", 0): ("qi_sent", 1),
    ("at", 0): ("at_net", 1), ("at", 1): ("at_net", -1),
    ("ai", 0): ("ai_net", 2),
}

# operations whose effect depends on the order the threads ran in: the final state of that resource is not printed
NONCOMM = {("ls", 3), ("ls", 5), ("st", 0), ("st", 1), ("st", 3), ("li", 3), ("bx", 0), ("bx", 1), ("bx", 3), ("at", 3), ("at", 4)}

HELPERS = """fn drain_q(q: read Arc[Queue[string]], got: read Arc[AtomicI64]):
    while true:
        match q.value.recv():
            Valid(x):
                got.value.fetch_and_add(1)
            None:
                break

fn drain_qm(q: read Arc[Queue[Msg]], got: read Arc[AtomicI64]):
    while true:
        match q.value.recv():
            Valid(x):
                got.value.fetch_and_add(1)
            None:
                break

fn drain_qi(q: read Arc[Queue[Item]], got: read Arc[AtomicI64]):
    while true:
        match q.value.recv():
            Valid(x):
                got.value.fetch_and_add(x.n * 0 + 1)
            None:
                break

fn two() -> List[string]:
    xs = List[string]()
    xs.push(string.from("a"))
    xs.push(string.from("b"))
    return xs

fn three() -> List[i32]:
    xs = List[i32]()
    xs.push(1)
    xs.push(2)
    xs.push(3)
    return xs

fn print_nothing(n: usize):
    if n > 1000000:
        print(n)

"""


def inner_helpers() -> str:
    """`inner_<k>`: runs every operation of resource `k` once; a worker may start it on a thread of its own."""
    out = []
    for k, ops in OPS.items():
        out.append(f"fn inner_{k}({k}: read {RES[k][0]}):")
        out.append("    for i in 0..3:")
        for code in ops:
            code = code.replace("r.value", f"{k}.value").replace("r.clone", f"{k}.clone")
            out.append("        if true:")
            for ln in code.split("\n"):
                out.append("            " + ln)
        out.append("")
    return "\n".join(out) + "\n"


class Gen:
    def __init__(self, rng: random.Random):
        self.r = rng
        self.noncomm: set[str] = set()

    def worker(self, idx: int, res: list[str], iters: int, nested: bool) -> tuple[str, dict]:
        r = self.r
        counts: dict[str, int] = {}
        params = ", ".join(f"{k}: read {RES[k][0]}" for k in res)
        lines = [f"fn worker{idx}({params}):", f"    for i in 0..{iters}:"]
        body: list[str] = []
        late: list[str] = []
        for _ in range(r.randint(1, 5)):
            k = r.choice(res)
            j = r.randrange(len(OPS[k]))
            code = OPS[k][j]
            if r.random() < 0.18:  # another thread runs the resource's operations while this one goes on
                nest = f"c_{len(body)} = {k}.clone()\nth_{len(body)} = Thread.spawn(fn() => inner_{k}(c_{len(body)}))"
                if r.random() < 0.7:
                    nest += f"\nth_{len(body)}.join()"
                else:  # this thread keeps working on the same resource before it joins
                    mine = OPS[k][r.randrange(len(OPS[k]))].replace("r.value", f"{k}.value").replace("r.clone", f"{k}.clone")
                    nest += "\n" + mine + f"\nth_{len(body)}.join()"
                body.append(nest)
                for jj, op_ in enumerate(OPS[k]):
                    if (k, jj) in NONCOMM:
                        self.noncomm.add(k)
                continue
            # the resource is called `r` inside the op; rename to the parameter
            code = code.replace("r.value", f"{k}.value").replace("r.clone", f"{k}.clone")
            body.append(code)
            if (k, j) in NONCOMM:
                self.noncomm.add(k)
            c = COUNT.get((k, j))
            if c:
                counts[c[0]] = counts.get(c[0], 0) + c[1]
        # a variable name used twice in one block is fine (reassignment), but keep each op in its own `if true:`
        for code in body:
            lines.append("        if true:")
            for ln in code.split("\n"):
                lines.append("            " + ln)
        for code in late:
            lines.append("        if true:")
            lines.append("            " + code)
        if len(lines) == 2:
            lines.append("        pass")
        return "\n".join(lines) + "\n\n", {k: v * iters for k, v in counts.items()}

    def program(self) -> str:
        r = self.r
        nres = r.randint(1, 5)
        keys = r.sample(list(RES), nres)
        nthreads = r.randint(2, 4)
        out = [HEADER, HELPERS, inner_helpers()]
        totals: dict[str, int] = {}
        main = ["fn main():"]
        for k in keys:
            main.append(f"    {k} = {RES[k][1]}")
        queue_keys = [k for k in keys if k in ("q", "qm", "qi")]
        workers = []
        for t in range(nthreads):
            res = r.sample(keys, r.randint(1, len(keys)))
            iters = r.randint(1, 30)
            code, cnt = self.worker(t, res, iters, False)
            out.append(code)
            for a, b in cnt.items():
                totals[a] = totals.get(a, 0) + b
            workers.append((t, res))
        # drained queues: a consumer thread per queue key reads until the queue is closed
        main.append("    got = Arc[AtomicI64](AtomicI64.new(0))")
        consumers = []
        for k in queue_keys:
            for c in range(r.randint(1, 2)):
                main.append(f"    got_{k}{c} = got.clone()")
                main.append(f"    {k}_c{c} = {k}.clone()")
                main.append(f"    c_{k}{c} = Thread.spawn(fn() => drain_{k}({k}_c{c}, got_{k}{c}))")
                consumers.append(f"c_{k}{c}")
        for t, res in workers:
            for k in res:
                main.append(f"    {k}_{t} = {k}.clone()")
            args = ", ".join(f"{k}_{t}" for k in res)
            main.append(f"    t{t} = Thread.spawn(fn() => worker{t}({args}))")
        if r.random() < 0.5:  # main works too
            main.append(f"    for i in 0..{r.randint(1, 10)}:")
            main.append("        pass")
        for t, _ in workers:
            main.append(f"    t{t}.join()")
        for k in queue_keys:
            main.append(f"    {k}.value.close()")
        for c in consumers:
            main.append(f"    {c}.join()")
        main.append("    print(\"joined\")")
        if queue_keys:
            main.append("    print(got.value.load())")
        for k in keys:
            if k in self.noncomm:
                continue
            if k == "ls":
                main.append("    print(ls.value.get().len)")
            elif k == "st":
                main.append("    print(st.value.get().len)")
            elif k == "li":
                main.append("    print(li.value.get().len)")
            elif k == "ms":
                main.append("    gg_o = ms.value.get()")
            elif k == "bx":
                main.append("    print(bx.value.get().value.vals.len)")
            elif k in ("at",):
                main.append("    print(at.value.load())")
            elif k == "ai":
                main.append("    print(ai.value.load())")
            elif k == "ro":
                main.append("    print(ro.value.label)")
        out.append("\n".join(main) + "\n")
        return "".join(out)


def work(args):
    idx, seed, workdir = args
    rng = random.Random(f"{seed}:{idx}")
    src = Gen(rng).program()
    ok, err = O.accepted(src)
    res = {"idx": idx, "status": "rejected", "error": err[:300]}
    if not ok:
        return res
    v = O.check_program(src, Path(workdir), name=f"t{idx}")
    res["status"] = "leak" if (v.kind == "ok" and v.live) else v.kind
    res["detail"] = v.detail
    if res["status"] not in ("ok", "rejected"):
        res["src"] = src
        res["errors"] = v.errors
        res["leak"] = v.stdout_leak[-200:].decode("utf-8", "replace")
        res["poison"] = v.stdout_poison[-200:].decode("utf-8", "replace")
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=100)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--jobs", type=int, default=6)
    ap.add_argument("--out", default="")
    ap.add_argument("--show", type=int, default=-1)
    a = ap.parse_args()
    if a.show >= 0:
        print(Gen(random.Random(f"{a.seed}:{a.show}")).program())
        return
    out = Path(a.out) if a.out else None
    if out:
        out.mkdir(parents=True, exist_ok=True)
    work_dir = tempfile.mkdtemp(prefix="ggthr_")
    tally: dict[str, int] = {}
    errors: dict[str, int] = {}
    with ProcessPoolExecutor(a.jobs) as ex:
        for res in ex.map(work, [(i, a.seed, work_dir) for i in range(a.count)]):
            tally[res["status"]] = tally.get(res["status"], 0) + 1
            if res["status"] == "rejected":
                key = res["error"][:90]
                errors[key] = errors.get(key, 0) + 1
            elif res["status"] != "ok" and out:
                (out / f"{res['status']}_{res['idx']:04d}.gg").write_text(
                    f"# {res.get('detail')!r} leak={res.get('leak')!r} poison={res.get('poison')!r} {res.get('errors')!r}\n"
                    + res["src"], encoding="utf-8")
    print(tally)
    for k, n in sorted(errors.items(), key=lambda kv: -kv[1])[:12]:
        print(f"  {n:4d} rejected: {k}")


if __name__ == "__main__":
    main()
