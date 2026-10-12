"""`for i in N`, `step`, indexed/mutable-reference `for`, and scalar (integer/char/bool/string) `match`."""
import subprocess
import sys

import pytest

from greengold.ast_nodes import For, ForIn, Match, RangePat

from .helpers import HAS_CC, ROOT, front_end, messages, run_gg_source


def has(msgs: list[str], text: str) -> bool:
    return any(text in m for m in msgs)


def _both(tmp_path, src: str) -> str:
    """Runs the program and returns its stdout."""
    llvm = run_gg_source(tmp_path, src)
    assert llvm.returncode == 0, llvm.stderr
    return llvm.stdout


# --- parser / type checker ----------------------------------------------------

def test_parse_for_variants():
    prog, diags = front_end("fn main():\n    for i in 5:\n        pass\n    for i in 0..9 step 2:\n        pass\n"
                            "    for k, x in [1, 2]:\n        pass\n    a = [1]\n    for x in a:\n        x += 1\n")
    assert not diags
    body = prog.decls[0].body if hasattr(prog, "decls") else None
    stmts = [s for s in body if isinstance(s, (For, ForIn))]
    assert isinstance(stmts[0], ForIn) and stmts[0].count
    assert isinstance(stmts[1], For) and stmts[1].step_value == 2
    assert stmts[2].index_var == "k"
    assert stmts[3].mutable


def test_parse_scalar_match():
    prog, diags = front_end("fn main():\n    x = 3\n    match x:\n        1 | 2:\n            pass\n"
                            "        3..=5:\n            pass\n        _:\n            pass\n")
    assert not diags
    m = next(s for s in prog.decls[0].body if isinstance(s, Match))
    assert len(m.arms[0].pats) == 2
    assert isinstance(m.arms[1].pats[0], RangePat)
    assert m.scalar_ty == "i32"


def test_err_for_over_float():
    assert has(messages("fn main():\n    f = 1.5\n    for i in f:\n        pass\n"), "Cannot iterate")


def test_err_assign_to_loop_ref_of_temporary():
    src = "struct E:\n    hp: i32\n\nfn make() -> [1]E:\n    return [E{hp: 1}]\n\nfn main():\n    for e in make():\n        e.hp = 2\n"
    assert has(messages(src), "element of a temporary value")
    nums = "fn make() -> [2]i32:\n    return [1, 2]\n\nfn main():\n    for n in make():\n        n += 1\n"
    assert has(messages(nums), "element of a temporary value")


def test_err_changing_loop_needs_changeable_iterable():
    src = "struct E:\n    hp: i32\n\nfn main():\n    fixed a = [E{hp: 1}]\n    for e in a:\n        e.hp = 2\n"
    assert has(messages(src), "declared `fixed`")
    assert not messages(src.replace("fixed a", "a"))


def test_err_step_zero_and_unsigned_negative():
    assert has(messages("fn main():\n    for i in 0..3 step 0:\n        pass\n"), "cannot be zero")
    assert has(messages("fn main():\n    n: u32 = 3\n    for i in 0..n step -1:\n        pass\n"), "unsigned")


def test_err_match_missing_default():
    assert has(messages("fn main():\n    x = 1\n    match x:\n        1:\n            pass\n"), "does not cover")


def test_err_match_bool_missing_arm():
    src = "fn main():\n    b = true\n    match b:\n        true:\n            pass\n"
    assert has(messages(src), "missing `false`")


def test_err_match_type_mismatch_and_duplicate():
    src = "fn main():\n    x = 1\n    match x:\n        'a':\n            pass\n        _:\n            pass\n"
    assert has(messages(src), "Type mismatch")
    src = "fn main():\n    x = 1\n    match x:\n        1:\n            pass\n        1:\n            pass\n        _:\n            pass\n"
    assert has(messages(src), "unreachable pattern")


def test_match_bool_and_full_range_are_exhaustive():
    assert not messages("fn main():\n    b = true\n    match b:\n        true:\n            pass\n        false:\n            pass\n")
    src = "fn main():\n    x: u8 = 3\n    match x:\n        0..=127:\n            pass\n        128..=255:\n            pass\n"
    assert not messages(src)


def test_err_literal_pattern_on_enum():
    src = "enum E:\n    A\n    B\n\nfn main():\n    e = E.A\n    match e:\n        1:\n            pass\n        _:\n            pass\n"
    assert has(messages(src), "Literal/range patterns")


# --- execution (LLVM and C99 must agree) ------------------------------------------

def test_run_for_forms(tmp_path):
    src = """\
fn main():
    for i in 3:
        print("c", i)
    for i in 0..10 step 4:
        print("s", i)
    for i in 0..=8 step 4:
        print("si", i)
    for i in 5..0 step -2:
        print("d", i)
    for k, x in [7, 8]:
        print("k", k, x)
    for i in 0:
        print("never")
"""
    out = _both(tmp_path, src).split("\n")
    assert out[:3] == ["c 0", "c 1", "c 2"]
    assert out[3:6] == ["s 0", "s 4", "s 8"]
    assert out[6:9] == ["si 0", "si 4", "si 8"]
    assert out[9:12] == ["d 5", "d 3", "d 1"]
    assert out[12:14] == ["k 0 7", "k 1 8"]
    assert "never" not in out


def test_run_step_no_overflow_u8(tmp_path):
    src = "fn main():\n    n: u8 = 255\n    c = 0\n    for i in 0..n step 100:\n        c += 1\n    print(c)\n"
    assert _both(tmp_path, src) == "3\n"


def test_run_for_struct_ref_and_mutation(tmp_path):
    src = """\
struct Entity:
    hp: i32
    id: i32

fn main():
    ents = [Entity{hp: 1, id: 1}, Entity{hp: 2, id: 2}]
    for e in ents:
        e.hp += 10
    for e in ents:
        e = Entity{hp: e.hp * 2, id: e.id}
    for e in ents:
        print(e.id, e.hp)
    nums = [1, 2, 3]
    for n in nums:
        n *= 3
    print(nums[0], nums[2])
"""
    assert _both(tmp_path, src) == "1 22\n2 24\n3 9\n"


def test_run_match_scalar(tmp_path):
    src = """\
fn name(n: i32) -> str:
    return match n:
        1 => "one"
        2 | 3 => "few"
        4..=9 => "some"
        -1 => "minus"
        _ => "many"

fn cmd(s: str) -> i32:
    match s:
        "a" | "b":
            return 1
        "":
            return 2
        _:
            return 0
    return 9

fn main():
    print(name(1), name(3), name(7), name(-1), name(50))
    print(cmd("b"), cmd(""), cmd("zz"))
    c = 'x'
    match c:
        'a'..='m':
            print("first half")
        'n'..='z':
            print("second half")
        _:
            pass
    for i in 5:
        match i:
            1:
                continue
            3:
                break
            _:
                print("i", i)
"""
    assert _both(tmp_path, src) == "one few some minus many\n1 2 0\nsecond half\ni 0\ni 2\n"


def test_for_in_generic_and_comptime(tmp_path):
    src = """\
fn g[T](xs: []T) -> i32:
    n = 0
    for i, x in xs:
        n += i32(i)
    return n

comptime fn sq(n: i32) -> i32:
    t = 0
    for i in n:
        t += i
    return t

fn main():
    print(g([5, 6, 7]), sq(4))
"""
    assert _both(tmp_path, src) == "3 6\n"
