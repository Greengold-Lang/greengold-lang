"""Mutation fuzzer for the memory-safety guarantee.

Takes the working programs of the repository (every feature the examples, the spec, and the tutorial use),
applies random edits that tend to break ownership, and keeps the mutants the compiler still ACCEPTS. Each
accepted mutant is built with the oracle allocator (`safety_oracle.py`) and run with a leaking and with a
poisoning heap. A different result means the checker let through a program that reads freed memory, frees
twice, or crashes: a hole in the guarantee.

    python tools/fuzz_safety.py --count 2000 --seed 1 --jobs 10 --out findings/
    python tools/fuzz_safety.py --replay findings/hole_000.gg        # run one saved program again
"""
from __future__ import annotations

import argparse
import collections
import random
import re
import sys
import tempfile
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

import safety_corpus  # noqa: E402
import safety_oracle as O  # noqa: E402

BAD_KINDS = ("mismatch", "double_free", "crash", "write_after_free", "heap_overflow", "leak")

# Helpers that every mutant may call: they force a move, a read, or a mutable borrow of any variable.
HELPERS = '''fn gg_sink[T](gg_x: consume T):
    pass

fn gg_peek[T](gg_x: read T):
    pass

fn gg_touch[T](gg_x: lend T):
    pass

'''


# ---------------------------------------------------------------- source structure
def indent_of(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def is_code(line: str) -> bool:
    s = line.strip()
    return bool(s) and not s.startswith("#")


def block_end(lines: list[str], i: int) -> int:
    """Index after the statement at `i` and everything nested under it (plus `else`/`elif` siblings)."""
    k = indent_of(lines[i])
    j = i + 1
    while j < len(lines):
        if is_code(lines[j]):
            ind = indent_of(lines[j])
            if ind < k or (ind == k and not lines[j].lstrip().startswith(("else", "elif"))):
                break
        j += 1
    # drop trailing blank lines from the block
    while j > i + 1 and not lines[j - 1].strip():
        j -= 1
    return j


def functions(lines: list[str]) -> list[tuple[int, int]]:
    """(start, end) of each function body: the lines after a top-level `fn` or an indented method `fn`."""
    out = []
    for i, l in enumerate(lines):
        m = re.match(r"^(\s*)(pub\s+|public\s+)?(async\s+)?(comptime\s+)?fn\s+\w+", l)
        if m and l.rstrip().endswith(":"):
            k = indent_of(l)
            j = i + 1
            while j < len(lines) and (not is_code(lines[j]) or indent_of(lines[j]) > k):
                j += 1
            while j > i + 1 and not lines[j - 1].strip():
                j -= 1
            out.append((i + 1, j))
    return out


def statements(lines: list[str], fn: tuple[int, int]) -> list[int]:
    """Indexes of lines in a function body that start a statement (not `else`/`elif`/`case` continuations)."""
    s, e = fn
    out = []
    for i in range(s, e):
        if is_code(lines[i]) and not lines[i].lstrip().startswith(("else", "elif")):
            out.append(i)
    return out


def bindings(lines: list[str], fn: tuple[int, int]) -> list[str]:
    """Names the function binds or takes (parameters, `x = ...`, `fixed x = ...`, `for x in`)."""
    s, e = fn
    names: list[str] = []
    head = lines[s - 1]
    for m in re.finditer(r"[(,]\s*(\w+)\s*:", head):
        names.append(m.group(1))
    for i in range(s, e):
        for m in re.finditer(r"^\s*(?:fixed\s+)?(\w+)(?:\s*:\s*[^=]+)?\s*=(?!=)", lines[i]):
            names.append(m.group(1))
        for m in re.finditer(r"\bfor\s+(\w+)(?:\s*,\s*(\w+))?\s+in\b", lines[i]):
            names += [g for g in m.groups() if g]
    return [n for n in dict.fromkeys(names) if n not in ("self", "_")]


# ---------------------------------------------------------------- mutation operators
def reindent(block: list[str], new_indent: int) -> list[str]:
    old = indent_of(block[0])
    d = new_indent - old
    out = []
    for l in block:
        if not l.strip():
            out.append(l)
        elif d >= 0:
            out.append(" " * d + l)
        else:
            out.append(l[min(-d, indent_of(l)):])
    return out


def pick_fn(lines, rng):
    fns = [f for f in functions(lines) if statements(lines, f)]
    return rng.choice(fns) if fns else None


def op_delete(lines, rng):
    f = pick_fn(lines, rng)
    if not f:
        return None
    i = rng.choice(statements(lines, f))
    return lines[:i] + lines[block_end(lines, i):]


def op_duplicate(lines, rng):
    f = pick_fn(lines, rng)
    if not f:
        return None
    i = rng.choice(statements(lines, f))
    e = block_end(lines, i)
    return lines[:e] + lines[i:e] + lines[e:]


def op_swap(lines, rng):
    f = pick_fn(lines, rng)
    if not f:
        return None
    i = rng.choice(statements(lines, f))
    e = block_end(lines, i)
    if e >= len(lines) or not is_code(lines[e]) or indent_of(lines[e]) != indent_of(lines[i]):
        return None
    e2 = block_end(lines, e)
    return lines[:i] + lines[e:e2] + lines[i:e] + lines[e2:]


def op_move(lines, rng):
    f = pick_fn(lines, rng)
    if not f:
        return None
    sts = statements(lines, f)
    i = rng.choice(sts)
    e = block_end(lines, i)
    block = lines[i:e]
    rest = lines[:i] + lines[e:]
    f2 = pick_fn(rest, rng)
    if not f2:
        return None
    targets = statements(rest, f2)
    t = rng.choice(targets)
    if rng.random() < 0.5:  # after the target's own block instead of before it
        t = block_end(rest, t)
    ind = indent_of(rest[min(t, len(rest) - 1)])
    return rest[:t] + reindent(block, ind) + rest[t:]


def op_insert_use(lines, rng):
    f = pick_fn(lines, rng)
    if not f:
        return None
    names = bindings(lines, f)
    if not names:
        return None
    n = rng.choice(names)
    n2 = rng.choice(names)
    t = rng.choice(statements(lines, f))
    if rng.random() < 0.5:
        t = block_end(lines, t)
    ind = indent_of(lines[min(t, len(lines) - 1)])
    stmt = rng.choice([
        f"print({n})", f"print({n})", f"gg_sink({n})", f"gg_peek({n})", f"gg_touch({n})",
        f"{n2} = {n}", f"gg_tmp{rng.randint(0, 9)} = {n}", f"{n} = {n2}",
        f"print({n}.len)", f"{n}.clear()", f"gg_tmp{rng.randint(0, 9)} = {n}.clone()",
    ])
    return lines[:t] + [" " * ind + stmt] + lines[t:]


def op_wrap(lines, rng):
    f = pick_fn(lines, rng)
    if not f:
        return None
    i = rng.choice(statements(lines, f))
    e = block_end(lines, i)
    ind = indent_of(lines[i])
    head = rng.choice(["if true:", "if false:", "for gg_i in 0..2:", "while false:"])
    inner = [("    " + l if l.strip() else l) for l in lines[i:e]]
    return lines[:i] + [" " * ind + head] + inner + lines[e:]


def op_remove_clone(lines, rng):
    idx = [i for i, l in enumerate(lines) if ".clone()" in l]
    if not idx:
        return None
    i = rng.choice(idx)
    parts = lines[i].split(".clone()")
    k = rng.randrange(len(parts) - 1)
    new = ".clone()".join(parts[:k + 1]) + "".join(
        (p if j == 0 else ".clone()" + p) for j, p in enumerate(parts[k + 1:]))
    # remove the k-th occurrence only
    pieces = lines[i].split(".clone()")
    s = pieces[0]
    for j in range(1, len(pieces)):
        s += ("" if j - 1 == k else ".clone()") + pieces[j]
    out = list(lines)
    out[i] = s
    return out


MODES = ["read ", "lend ", "consume ", ""]


def op_flip_mode(lines, rng):
    idx = [i for i, l in enumerate(lines) if re.match(r"^\s*(?:pub\s+)?(?:async\s+)?fn\s+\w+.*\(.*\w+\s*:", l)]
    if not idx:
        return None
    i = rng.choice(idx)
    l = lines[i]
    m = list(re.finditer(r"(\w+)\s*:\s*((?:read|lend|consume|send)\s+)?(?=[\[\]\w*&])", l))
    m = [x for x in m if x.group(1) not in ("tied",)]
    if not m:
        return None
    x = rng.choice(m)
    new = rng.choice(MODES)
    out = list(lines)
    out[i] = l[:x.start(2) if x.group(2) else x.end()] + new + l[x.end():]
    return out


def op_drop_fixed(lines, rng):
    idx = [i for i, l in enumerate(lines) if re.search(r"\bfixed\s", l)]
    if not idx:
        return None
    i = rng.choice(idx)
    out = list(lines)
    out[i] = re.sub(r"\bfixed\s+", "", out[i], count=1)
    return out


def op_replace_ident(lines, rng):
    f = pick_fn(lines, rng)
    if not f:
        return None
    names = bindings(lines, f)
    if len(names) < 2:
        return None
    a, b = rng.sample(names, 2)
    cand = [i for i in range(f[0], f[1]) if re.search(rf"\b{re.escape(a)}\b", lines[i]) and is_code(lines[i])]
    if not cand:
        return None
    i = rng.choice(cand)
    occ = list(re.finditer(rf"\b{re.escape(a)}\b", lines[i]))
    m = rng.choice(occ)
    out = list(lines)
    out[i] = lines[i][:m.start()] + b + lines[i][m.end():]
    return out


def op_control(lines, rng):
    f = pick_fn(lines, rng)
    if not f:
        return None
    t = rng.choice(statements(lines, f))
    ind = indent_of(lines[t])
    kw = rng.choice(["return", "break", "continue"])
    return lines[:t] + [" " * ind + kw] + lines[t:]


def op_dup_decl(lines, rng):
    """Copies a binding under a second name (`b = a`): an alias of the value that may be moved or kept."""
    f = pick_fn(lines, rng)
    if not f:
        return None
    sts = [i for i in statements(lines, f) if re.match(r"^\s*(?:fixed\s+)?\w+\s*=(?!=)", lines[i])]
    if not sts:
        return None
    i = rng.choice(sts)
    m = re.match(r"^(\s*)(?:fixed\s+)?(\w+)\s*=(?!=)\s*(.*)$", lines[i])
    ind, name, rhs = m.groups()
    e = block_end(lines, i)
    return lines[:e] + [f"{ind}gg_alias = {name}"] + lines[e:] if rng.random() < 0.5 else \
        lines[:i] + [f"{ind}gg_alias = {rhs}"] + lines[i:]


OPERATORS = [
    (op_delete, 3), (op_duplicate, 3), (op_swap, 3), (op_move, 4), (op_insert_use, 8), (op_wrap, 2),
    (op_remove_clone, 3), (op_flip_mode, 4), (op_drop_fixed, 1), (op_replace_ident, 4), (op_control, 2),
    (op_dup_decl, 2),
]


def mutate(src: str, rng: random.Random, n_ops: int | None = None) -> tuple[str, list[str]]:
    lines = src.rstrip("\n").split("\n")
    used = []
    ops, weights = zip(*OPERATORS)
    for _ in range(n_ops or rng.choice([1, 1, 2, 2, 3])):
        for _try in range(8):
            op = rng.choices(ops, weights)[0]
            out = op(lines, rng)
            if out is not None and out != lines:
                lines = out
                used.append(op.__name__[3:])
                break
    return "\n".join(lines) + "\n", used


def add_helpers(src: str) -> str:
    """The helpers go after the leading imports, before the first declaration."""
    lines = src.splitlines(keepends=True)
    i = 0
    while i < len(lines) and (not lines[i].strip() or lines[i].lstrip().startswith(("import ", "#"))):
        i += 1
    return "".join(lines[:i]) + HELPERS + "".join(lines[i:])


# ---------------------------------------------------------------- driver
def work(args):
    """One mutant. Returns a dict describing what happened."""
    seed_idx, name, src, seed, mut_idx, workdir = args
    rng = random.Random(f"{seed}:{mut_idx}")
    mutant, ops = mutate(src, rng)
    full = add_helpers(mutant)
    ok, err = O.accepted(full)
    res = {"seed": name, "ops": ops, "status": "rejected", "error": err[:200]}
    if not ok:
        return res
    v = O.check_program(full, Path(workdir), name=f"m{mut_idx}")
    res["status"] = "leak" if (v.kind == "ok" and v.live) else v.kind
    res["detail"] = v.detail
    if res["status"] in BAD_KINDS or v.kind in ("build_error",):
        res["src"] = full
        res["leak"] = v.stdout_leak[-300:].decode("utf-8", "replace")
        res["poison"] = v.stdout_poison[-300:].decode("utf-8", "replace")
        res["errors"] = v.errors
    return res


def load_seeds() -> list[tuple[str, str]]:
    seeds = []
    for name, src in safety_corpus.collect().items():
        if O.UNSAFE_WORDS.search(src):
            continue
        ok, _ = O.accepted(add_helpers(src))
        if ok:
            seeds.append((name, src))
    return seeds


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=500)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--jobs", type=int, default=8)
    ap.add_argument("--out", default="")
    ap.add_argument("--replay", default="")
    a = ap.parse_args()
    if a.replay:
        v = O.check_program(Path(a.replay).read_text(encoding="utf-8"), Path(tempfile.mkdtemp(prefix="ggreplay_")))
        print(v.kind, v.detail)
        print("leak  :", v.stdout_leak[-200:])
        print("poison:", v.stdout_poison[-200:])
        return 0 if v.kind not in BAD_KINDS else 1
    seeds = load_seeds()
    print(f"{len(seeds)} seed programs", flush=True)
    workdir = tempfile.mkdtemp(prefix="ggfuzz_")
    out = Path(a.out) if a.out else None
    if out:
        out.mkdir(parents=True, exist_ok=True)
    jobs = []
    for i in range(a.count):
        r = random.Random(f"{a.seed}:pick:{i}")
        si = r.randrange(len(seeds))
        jobs.append((si, seeds[si][0], seeds[si][1], a.seed, i, workdir))
    stats = collections.Counter()
    ops_ok = collections.Counter()
    findings = []
    t0 = time.time()
    with ProcessPoolExecutor(a.jobs) as ex:
        for n, res in enumerate(ex.map(work, jobs, chunksize=4)):
            stats[res["status"]] += 1
            if res["status"] == "ok":
                for o in res["ops"]:
                    ops_ok[o] += 1
            if res["status"] in BAD_KINDS:
                findings.append(res)
                if out:
                    p = out / f"{res['status']}_{len(findings) - 1:03d}.gg"
                    p.write_text(f"# seed {res['seed']} ops {res['ops']}: {res['detail']!r}\n# leak: {res.get('leak')!r}\n"
                                 f"# poison: {res.get('poison')!r}\n" + res["src"], encoding="utf-8")
            if (n + 1) % 200 == 0:
                print(f"  {n + 1}/{a.count}  {dict(stats)}  {time.time() - t0:.0f}s", flush=True)
    print(dict(stats))
    print("operators in accepted mutants:", dict(ops_ok))
    print(f"FINDINGS (accepted yet unsafe): {len(findings)}")
    for f in findings[:20]:
        print(f"  [{f['status']}] seed={f['seed']} ops={f['ops']} {f['detail']}")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
