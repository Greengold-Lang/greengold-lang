"""Enums whose variants carry nothing have numbers: `Red = 1`, `to_int`, `from_int`, `i32(e)`."""
from tests.helpers import front_end, run_built


def test_enum_numbers():
    src = """\
enum Color:
    Red = 1
    Green = 2
    Blue = 4

enum Dir:
    North
    South
    West = 10
    East

fn main():
    c = Color.Blue
    print(c.to_int(), Dir.South.to_int(), Dir.East.to_int(), Color.from_int(2), Color.from_int(3), i32(Color.Green))
"""
    assert run_built(src).stdout.strip() == "4 1 11 Valid(Color.Green) None 2"


def test_duplicate_numbers_and_payloads_are_rejected():
    _p, diags = front_end("enum E:\n    A = 1\n    B = 1\n\nfn main():\n    pass\n")
    assert any("same number" in d.message for d in diags)
    _p, diags = front_end("enum E:\n    A = 1(i32)\n\nfn main():\n    pass\n")
    assert diags


def test_own_to_int_is_kept():
    src = """\
enum E:
    A
    B

impl E:
    fn to_int(self) -> i64:
        return 42

fn main():
    print(E.B.to_int(), E.from_int(1))
"""
    assert run_built(src).stdout.strip() == "42 Valid(E.B)"
