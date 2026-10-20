"""Code coverage: statements, decisions, conditions, and MC/DC, for the evidence that safety standards ask for.

    gg run app.gg --coverage              # runs the program with counters, then prints the summary
    gg test --coverage tests/             # the same over every test; the counts add up across tests
    gg coverage report .gg-coverage       # prints the summary again, `--lcov out.info` writes LCOV, `--annotate` shows lines

How it works. Before type checking, every function in the program's own files (not the library, not `test` blocks) is rewritten:

* a counter bump `__cov_hit(id)` goes before each statement (statement coverage);
* each `if`/`elif`/`while` condition becomes `__cov_dec(d, <condition>)`, and each condition `a`, `b`, ... inside its `and`/`or`/`not`
  structure becomes `__cov_cond(d, i, a)`. The runtime keeps, per decision, which combinations of condition values were seen
  (a condition that short-circuiting skipped counts as "not evaluated") and which outcome each gave. That is enough to decide
  decision coverage (both outcomes seen), condition coverage (each condition seen true and false), and masking MC/DC (each condition
  has a pair of runs where only it, and what it masks, changed, and the outcome changed).
* `main` gets `defer __cov_dump()`, which appends the counts to the file named by `GG_COV_OUT` (default `.gg-coverage`).

The counters are plain globals: run coverage on single-threaded code, or accept small errors from races. A program that panics or
calls `process_exit` writes nothing for that run. The instrumented program is slower and bigger; it is for testing, not release.
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

from .ast_nodes import (
    Binary, Branch, Call, Defer, ExprStmt, For, ForIn, FuncDecl, If, IntLit, Match, Name, Stmt, Unary, While,
)

PACKAGE_DIR = Path(__file__).resolve().parent
MAX_CONDITIONS = 6          # decisions with more conditions get decision coverage only
ENV_ON = "GG_COVERAGE"
ENV_OUT = "GG_COV_OUT"
ENV_REMAP = "GG_COV_REMAP"  # "temporary file|original file": `gg test` runs copies, keys name the original


def enabled() -> bool:
    return os.environ.get(ENV_ON) == "1"


def _user_file(filename: str | None) -> bool:
    if not filename or filename.startswith("<"):
        return False
    try:
        return PACKAGE_DIR not in Path(filename).resolve().parents
    except OSError:
        return False


@dataclass
class _State:
    keys: list[str] = field(default_factory=list)               # statement keys, by id
    decisions: list[tuple[str, int]] = field(default_factory=list)   # (key, tracked conditions)
    remap: tuple[str, str] | None = None
    skip_main: bool = False

    def key(self, node, kind: str) -> str:
        name = getattr(node, "filename", None) or "?"
        if self.remap and Path(name).resolve() == Path(self.remap[0]).resolve():
            name = self.remap[1]
        return f"{Path(name).as_posix()}:{node.line}:{node.col}:{kind}"


def _call(name: str, *args, like=None) -> Call:
    c = Call(name, list(args))
    if like is not None:
        c.line, c.col, c.length, c.filename = like.line, like.col, like.length, getattr(like, "filename", None)
    return c


def _int(v: int, like=None) -> IntLit:
    n = IntLit(v)
    if like is not None:
        n.line, n.col, n.length, n.filename = like.line, like.col, like.length, getattr(like, "filename", None)
    return n


def _atoms(e, out: list) -> None:
    """The atomic conditions of a decision, left to right, as (parent, attribute-or-index) slots."""
    if isinstance(e, Binary) and e.op in ("and", "or"):
        _atoms_side(e, "left", out)
        _atoms_side(e, "right", out)
    elif isinstance(e, Unary) and e.op == "not":
        _atoms_side(e, "operand", out)


def _atoms_side(parent, attr: str, out: list) -> None:
    child = getattr(parent, attr)
    if isinstance(child, Binary) and child.op in ("and", "or") or isinstance(child, Unary) and child.op == "not":
        _atoms(child, out)
    else:
        out.append((parent, attr))


def _decision(st: _State, cond, owner_node):
    """`cond` rewritten with the decision and condition probes; returns the new expression."""
    from .ast_nodes import BoolLit
    if isinstance(cond, BoolLit):
        return cond
    did = len(st.decisions)
    slots: list = []
    if isinstance(cond, Binary) and cond.op in ("and", "or") or isinstance(cond, Unary) and cond.op == "not":
        _atoms(cond, slots)
    tracked = min(max(len(slots), 1), MAX_CONDITIONS)
    st.decisions.append((st.key(cond, "D"), tracked if len(slots) <= MAX_CONDITIONS else 0))
    if not slots or len(slots) > MAX_CONDITIONS:
        # one condition (or too many to track): the decision's own value is the only condition
        wrapped = _call("__cov_cond", _int(did, cond), _int(0, cond), cond, like=cond)
        return _call("__cov_dec", _int(did, cond), wrapped, like=cond)
    for i, (parent, attr) in enumerate(slots):
        leaf = getattr(parent, attr)
        setattr(parent, attr, _call("__cov_cond", _int(did, leaf), _int(i, leaf), leaf, like=leaf))
    return _call("__cov_dec", _int(did, cond), cond, like=cond)


def _hit(st: _State, stmt) -> Stmt:
    sid = len(st.keys)
    st.keys.append(st.key(stmt, "S"))
    s = ExprStmt(_call("__cov_hit", _int(sid, stmt), like=stmt))
    s.line, s.col, s.length, s.filename = stmt.line, stmt.col, stmt.length, getattr(stmt, "filename", None)
    return s


def _block(st: _State, stmts: list) -> list:
    out: list = []
    for s in stmts:
        if not isinstance(s, Stmt):
            out.append(s)
            continue
        if isinstance(s, If):
            if not s.unsafe:
                out.append(_hit(st, s))
            for br in s.branches:
                if not s.unsafe:
                    br.cond = _decision(st, br.cond, br)
                br.body = _block(st, br.body)
            if s.else_body is not None:
                s.else_body = _block(st, s.else_body)
        elif isinstance(s, While):
            out.append(_hit(st, s))
            s.cond = _decision(st, s.cond, s)
            s.body = _block(st, s.body)
        elif isinstance(s, (For, ForIn)):
            out.append(_hit(st, s))
            s.body = _block(st, s.body)
        elif isinstance(s, Match):
            out.append(_hit(st, s))
            for arm in s.arms:
                arm.body = _block(st, arm.body)
        elif isinstance(s, Defer):
            pass
        else:
            out.append(_hit(st, s))
        out.append(s)
    return out


RUNTIME = '''
extern "stdio.h" fn fopen(path: str, mode: str) -> *mut u8 as __cov_fopen
extern "stdio.h" fn fclose(f: *mut u8) -> i32 as __cov_fclose
extern "stdio.h" fn fprintf(f: *mut u8, fmt: str, ...) -> i32 as __cov_fprintf
extern "stdlib.h" fn getenv(name: str) -> *u8 as __cov_getenv

static __cov_hits: [{S}]u32 = [0; {S}]
static __cov_cur: [{D}]u32 = [0; {D}]
static __cov_seen: [{V}]u8 = [0; {V}]
const __cov_keys: [{S}]str = [{KEYS}]
const __cov_dkeys: [{D}]str = [{DKEYS}]
const __cov_dn: [{D}]u32 = [{DN}]
const __cov_dbase: [{D}]u32 = [{DBASE}]
const __cov_pow3: [7]u32 = [1, 3, 9, 27, 81, 243, 729]

fn __cov_hit(id: u32):
    unsafe:
        __cov_hits[id] = wrapping_add[u32](__cov_hits[id], 1)

fn __cov_cond(d: u32, i: u32, v: bool) -> bool:
    unsafe:
        n = __cov_dn[d]
        if n > 0:
            cur: u32 = __cov_cur[d]
            if i == 0:
                cur = __cov_pow3[n] - 1
            digit: u32 = 0
            if v:
                digit = 1
            if i < n:
                cur = cur - 2 * __cov_pow3[i] + digit * __cov_pow3[i]
            __cov_cur[d] = cur
    return v

fn __cov_dec(d: u32, r: bool) -> bool:
    unsafe:
        n = __cov_dn[d]
        out: u32 = 0
        if r:
            out = 1
        if n > 0:
            __cov_seen[__cov_dbase[d] + __cov_cur[d] * 2 + out] = 1
        else:
            __cov_seen[__cov_dbase[d] + out] = 1
    return r

fn __cov_dump():
    unsafe:
        env = __cov_getenv("{ENV}")
        f: *mut u8 = null
        if env == null:
            f = __cov_fopen(".gg-coverage", "ab")
        else:
            f = __cov_fopen(cstr_to_string(env), "ab")
        if f == null:
            return
        for i in 0..{S}:
            __cov_fprintf(f, "K %s\\n", __cov_keys[i])
            if __cov_hits[i] > 0:
                __cov_fprintf(f, "H %s %u\\n", __cov_keys[i], __cov_hits[i])
        for d in 0..{D}:
            __cov_fprintf(f, "N %s %u\\n", __cov_dkeys[d], __cov_dn[d])
            cnt: u32 = 2
            if __cov_dn[d] > 0:
                cnt = __cov_pow3[__cov_dn[d]] * 2
            for j in 0..cnt:
                if __cov_seen[__cov_dbase[d] + j] != 0:
                    __cov_fprintf(f, "V %s %u\\n", __cov_dkeys[d], j)
        __cov_fclose(f)
'''


def _lit(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def instrument(program) -> None:
    """Rewrites the program's own functions and adds the runtime. Call before type checking."""
    from .diagnostics import DiagnosticBag
    from .lexer import tokenize
    from .parser import parse

    st = _State()
    remap = os.environ.get(ENV_REMAP)
    if remap and "|" in remap:
        st.remap = (remap.split("|", 1)[0], remap.split("|", 1)[1])
    main_decl = None
    for d in program.decls:
        if not isinstance(d, FuncDecl) or d.body is None or d.is_test or d.is_comptime or getattr(d, "from_prelude", False):
            continue
        if not _user_file(getattr(d, "filename", None)):
            continue
        if d.name == "main" and d.owner is None:
            main_decl = d
            if st.remap:
                continue      # the test harness's main is not part of the program under test
        d.body = _block(st, d.body)
    # the runtime: tables sized by what was found
    s_count = max(len(st.keys), 1)
    dn = [t for _, t in st.decisions]
    bases, total = [], 0
    for t in dn:
        bases.append(total)
        total += (3 ** t) * 2 if t > 0 else 2
    d_count = max(len(st.decisions), 1)
    if not st.decisions:
        dn, bases, total = [0], [0], 2
    text = (RUNTIME.replace("{S}", str(s_count)).replace("{D}", str(d_count)).replace("{V}", str(max(total, 1)))
            .replace("{KEYS}", ", ".join(_lit(k) for k in st.keys) if st.keys else '""')
            .replace("{DKEYS}", ", ".join(_lit(k) for k, _ in st.decisions) if st.decisions else '""')
            .replace("{DN}", ", ".join(str(t) for t in dn)).replace("{DBASE}", ", ".join(str(b) for b in bases))
            .replace("{ENV}", ENV_OUT))
    diags = DiagnosticBag()
    runtime = parse(tokenize(text, diags), diags)
    if diags.has_errors():
        raise RuntimeError("coverage runtime does not parse: " + diags.items[0].message)
    for d in runtime.decls:
        d.filename = "<coverage>"
        if hasattr(d, "is_pub"):
            d.is_pub = True
    program.decls.extend(runtime.decls)
    if main_decl is not None:
        dump = Defer(ExprStmt(_call("__cov_dump", like=main_decl)))
        dump.line, dump.col, dump.filename = main_decl.line, main_decl.col, getattr(main_decl, "filename", None)
        main_decl.body.insert(0, dump)


# -- reading and reporting --------------------------------------------------------------------------------------------

@dataclass
class Data:
    statements: dict[str, int] = field(default_factory=dict)     # key -> hits (0 when only listed)
    decisions: dict[str, int] = field(default_factory=dict)      # key -> number of tracked conditions
    seen: dict[str, set[int]] = field(default_factory=dict)      # key -> observed (vector * 2 + outcome)


def load(path: str | Path) -> Data:
    data = Data()
    for line in Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
        parts = line.split()
        if not parts:
            continue
        if parts[0] == "K" and len(parts) == 2:
            data.statements.setdefault(parts[1], 0)
        elif parts[0] == "H" and len(parts) == 3:
            data.statements[parts[1]] = data.statements.get(parts[1], 0) + int(parts[2])
        elif parts[0] == "N" and len(parts) == 3:
            data.decisions[parts[1]] = int(parts[2])
            data.seen.setdefault(parts[1], set())
        elif parts[0] == "V" and len(parts) == 3:
            data.seen.setdefault(parts[1], set()).add(int(parts[2]))
    return data


def _digits(vec: int, n: int) -> list[int]:
    return [(vec // 3 ** i) % 3 for i in range(n)]


def decision_metrics(n: int, seen: set[int]) -> tuple[bool, list[bool], list[bool]]:
    """(both outcomes seen, per-condition 'seen true and false', per-condition masking MC/DC)."""
    outcomes = {s % 2 for s in seen}
    both = outcomes == {0, 1}
    if n == 0:
        return both, [], []
    runs = [(_digits(s // 2, n), s % 2) for s in seen]
    cond_cov, mcdc = [], []
    for i in range(n):
        vals = {d[i] for d, _ in runs if d[i] != 2}
        cond_cov.append(vals == {0, 1})
        ok = False
        for a in range(len(runs)):
            da, oa = runs[a]
            if da[i] == 2:
                continue
            for b in range(a + 1, len(runs)):
                db, ob = runs[b]
                if db[i] == 2 or da[i] == db[i] or oa == ob:
                    continue
                # every other condition: equal, or masked (not evaluated) in one of the two runs
                if all(da[j] == db[j] or da[j] == 2 or db[j] == 2 for j in range(n) if j != i):
                    ok = True
                    break
            if ok:
                break
        mcdc.append(ok)
    return both, cond_cov, mcdc


@dataclass
class Summary:
    statements: tuple[int, int]
    decisions: tuple[int, int]
    conditions: tuple[int, int]
    mcdc: tuple[int, int]
    uncovered: list[str]
    gaps: list[str]


def summarize(data: Data) -> Summary:
    covered = sum(1 for h in data.statements.values() if h > 0)
    dec_c = dec_t = cond_c = cond_t = mc_c = mc_t = 0
    gaps: list[str] = []
    for key, n in data.decisions.items():
        both, cc, mc = decision_metrics(n, data.seen.get(key, set()))
        dec_t += 1
        dec_c += 1 if both else 0
        if not both:
            gaps.append(f"{_loc(key)}: decision never took both outcomes")
        cond_t += len(cc)
        cond_c += sum(cc)
        mc_t += len(mc)
        mc_c += sum(mc)
        for i, ok in enumerate(mc):
            if not ok:
                gaps.append(f"{_loc(key)}: condition {i + 1} has no MC/DC pair")
    unc = sorted((k for k, h in data.statements.items() if h == 0), key=_sortkey)
    return Summary((covered, len(data.statements)), (dec_c, dec_t), (cond_c, cond_t), (mc_c, mc_t), unc, gaps)


def _sortkey(key: str):
    file, line, col, _kind = key.rsplit(":", 3)
    return (file, int(line), int(col))


def _loc(key: str) -> str:
    file, line, col, _kind = key.rsplit(":", 3)
    return f"{file}:{line}:{col}"


def _pct(pair: tuple[int, int]) -> str:
    c, t = pair
    return "n/a" if t == 0 else f"{100.0 * c / t:5.1f}%  ({c}/{t})"


def format_summary(s: Summary, annotate: bool = False) -> str:
    out = ["coverage",
           f"  statements : {_pct(s.statements)}",
           f"  decisions  : {_pct(s.decisions)}",
           f"  conditions : {_pct(s.conditions)}",
           f"  MC/DC      : {_pct(s.mcdc)}"]
    if annotate:
        if s.uncovered:
            out.append("not executed:")
            out += [f"  {_loc(k)}" for k in s.uncovered]
        if s.gaps:
            out.append("decision gaps:")
            out += [f"  {g}" for g in s.gaps]
    return "\n".join(out)


def lcov(data: Data) -> str:
    """LCOV tracefile (line and branch records) for the usual viewers."""
    by_file: dict[str, dict[int, int]] = {}
    for key, hits in data.statements.items():
        file, line, _c, _k = key.rsplit(":", 3)
        lines = by_file.setdefault(file, {})
        lines[int(line)] = lines.get(int(line), 0) + hits
    branches: dict[str, list[tuple[int, int, int]]] = {}
    for key, n in data.decisions.items():
        file, line, _c, _k = key.rsplit(":", 3)
        seen = data.seen.get(key, set())
        outcomes = {s % 2 for s in seen}
        branches.setdefault(file, []).append((int(line), 0, 1 if 1 in outcomes else 0))
        branches[file].append((int(line), 1, 1 if 0 in outcomes else 0))
    out = []
    for file in sorted(by_file):
        out.append("TN:")
        out.append(f"SF:{file}")
        for line in sorted(by_file[file]):
            out.append(f"DA:{line},{by_file[file][line]}")
        out.append(f"LF:{len(by_file[file])}")
        out.append(f"LH:{sum(1 for h in by_file[file].values() if h > 0)}")
        brs = branches.get(file, [])
        for line, idx, taken in brs:
            out.append(f"BRDA:{line},0,{idx},{taken}")
        out.append(f"BRF:{len(brs)}")
        out.append(f"BRH:{sum(1 for _, _, t in brs if t)}")
        out.append("end_of_record")
    return "\n".join(out) + "\n"


def run_report(path: str, annotate: bool, lcov_out: str | None) -> int:
    if not Path(path).is_file():
        print(f"Error: no coverage data at {path}", file=sys.stderr)
        return 1
    data = load(path)
    print(format_summary(summarize(data), annotate))
    if lcov_out:
        Path(lcov_out).write_text(lcov(data), encoding="utf-8")
        print(f"LCOV written to {lcov_out}")
    return 0
