"""Regression tests for compiler crashes and miscompilations."""
from tests.helpers import run_built


def test_subslice_and_slice_param_passed_to_lend_slice():
    src = """\
fn zero(a: lend []i32):
    a[0] = 0

fn fwd(a: lend []i32):
    zero(a)
    zero(a[1..2])

fn total(a: []i32) -> i32:
    t = 0
    for x in a:
        t += x
    return t

fn main():
    nums = [3, 1, 2]
    fwd(nums)
    print(nums[0], nums[1], nums[2], total(nums[1..3]))
"""
    r = run_built(src)
    assert r.returncode == 0, r.stderr
    assert r.stdout.split() == ["0", "0", "2", "2"]


def test_try_converts_str_error_to_string():
    src = """\
fn digit(c: u8) -> Result[i32, str]:
    if c >= '0' and c <= '9':
        return Ok(i32(c - '0'))
    return Err("bad")

fn f(c: u8) -> Result[i32, string]:
    x = digit(c)?
    return Ok(x)

fn main():
    match f('7'):
        Ok(v):
            print(v)
        Err(e):
            print(e)
    match f('x'):
        Ok(v):
            print(v)
        Err(e):
            print(e)
"""
    r = run_built(src)
    assert r.returncode == 0, r.stderr
    assert r.stdout.split() == ["7", "bad"]


def test_bounded_int_is_printable():
    src = """\
const MASK: u32 = 0xFF

fn main():
    print("Mask:", MASK & 0x0F)
"""
    r = run_built(src)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "Mask: 15"


def test_named_types_do_not_leak_between_compilations():
    from greengold.cli import compile_to_ir
    compile_to_ir("struct Pair:\n    a: i32\n\nfn main():\n    p = Pair{ a: 1 }\n    print(p.a)\n")
    ir = compile_to_ir("fn main():\n    pass\n")
    assert "Pair" not in ir


def test_hashmap_with_builtin_hash_and_struct_keys():
    src = """\
import std.collections

struct Point:
    x: i32
    y: i32

impl Point:
    fn hash(self: Self) -> u64:
        return hash(self.x) ^ (hash(self.y) << 1)

    fn eq(self: Self, other: Point) -> bool:
        return self.x == other.x and self.y == other.y

fn main():
    ages = collections.hashmap_new[str, i32]()
    ages.insert("ada", 36)
    ages.insert("bob", 25)
    pts = collections.hashmap_new[Point, str]()
    pts.insert(Point{ x: 1, y: 2 }, "a")
    seen = collections.hashset_new[u64]()
    seen.insert(7)
    print(ages.get_or("ada", 0), ages.get_or("eve", -1), pts.get_or(Point{ x: 1, y: 2 }, "?"), seen.contains(7))
"""
    r = run_built(src)
    assert r.returncode == 0, r.stderr
    assert r.stdout.split() == ["36", "-1", "a", "true"]


def test_hash_builtin_rejects_unhashable_types():
    from tests.helpers import messages
    assert any("cannot be hashed" in m for m in messages("fn main():\n    print(hash(1.5))\n"))
    assert any("cannot be hashed" in m for m in messages(
        "struct Q:\n    a: f64\n\nfn main():\n    print(hash(Q{ a: 1.0 }))\n"))


def test_string_equality():
    r = run_built('fn main():\n    a = string.from("x")\n    print(a == string.from("x"), a != string.from("y"))\n')
    assert r.returncode == 0, r.stderr
    assert r.stdout.split() == ["true", "true"]


def test_owned_temporary_lent_to_a_call_is_freed(monkeypatch):
    monkeypatch.setenv("GG_LEAKCHECK", "1")
    src = """\
fn size(xs: List[i32]) -> usize:
    return xs.len

fn mk() -> List[i32]:
    v = List[i32]()
    v.push(1)
    return v

fn main():
    print(size(mk()), string.from("abc").len())
"""
    r = run_built(src)
    assert r.returncode == 0, r.stderr
    assert r.stdout.split() == ["1", "3"]
    assert "LEAK" not in r.stderr


def test_temporary_is_kept_when_the_result_points_into_it():
    r = run_built('import std.string\n\nfn main():\n    print(string.to_lower("MiXed").as_str())\n')
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "mixed"


def test_local_in_imported_module_does_not_clash_with_program_names():
    from tests.helpers import messages
    # std.thread has locals named `w`; the program's own `fn w` must not reach into that module
    src = 'import std.thread\n\nfn w():\n    print("w")\n\nfn main():\n    c = thread.Channel.new()\n'
    assert not any("conflicts with a function/struct name" in m for m in messages(src))
    # a clash inside the program itself is still reported
    assert any("conflicts with a function/struct name" in m for m in messages("fn w():\n    pass\n\nfn main():\n    w = 1\n"))


def test_snippet_found_for_a_file_in_a_subdirectory(tmp_path, capsys):
    """`gg check sub/a.gg` on Windows: the source is keyed `sub\a.gg`, a node may carry `sub/a.gg`."""
    from greengold.cli import cmd_check
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "t.gg").write_text("enum E:\n    A(i32)\n    B\n\nfn main():\n    e = E.A(1)\n    match e:\n"
                              "        B:\n            print(0)\n", encoding="utf-8")
    import os
    old = os.getcwd()
    os.chdir(tmp_path)
    try:
        cmd_check(["sub/t.gg"], False)
    finally:
        os.chdir(old)
    assert "7 |     match e:" in capsys.readouterr().err
