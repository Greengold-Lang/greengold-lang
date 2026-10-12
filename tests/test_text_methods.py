"""Text methods on `str` and `string` (core.gg `impl str:`), `List.join`, and freeing a list a `for` walks."""
from pathlib import Path

from tests.helpers import front_end, run_built, EXAMPLES_DIR

ROOT = Path(__file__).resolve().parents[1]


def _run(name, monkeypatch):
    monkeypatch.setenv("GG_LEAKCHECK", "1")
    r = run_built((EXAMPLES_DIR / name).read_text(encoding="utf-8"))
    assert r.returncode == 0, r.stderr
    assert "LEAK" not in r.stderr
    return r.stdout.splitlines()


def test_str_methods(monkeypatch):
    assert _run("text_methods.gg", monkeypatch) == [
        'a,b,,c ["a", "b", "", "c"] true true Valid(3) Valid(4) true',
        '["x", "y", "z"] ["l1", "l2"] ABC abc ababab',
        "a::b::c Valid(-42) Valid(350) None 2",
        "true prefix true",
    ]


def test_string_has_the_str_methods_and_lists_join(monkeypatch):
    assert _run("text_methods_owned.gg", monkeypatch) == [
        'Hello, World   HELLO, WORLD   true ["  Hello", " World  "]',
        "a-b-c x+y",
        "1, 2",
        "ann & bob",
        "60",
    ]


def test_for_over_a_fresh_list_frees_it(monkeypatch):
    monkeypatch.setenv("GG_LEAKCHECK", "1")
    src = """\
fn mk() -> List[string]:
    xs = List[string]()
    xs.push("a")
    xs.push("b")
    return xs

fn first() -> i32:
    for w in mk():
        if w.len() == 1:
            return 7
    return 0

fn main():
    for w in mk():
        print(w)
        break
    print(first())
"""
    r = run_built(src)
    assert r.returncode == 0, r.stderr
    assert "LEAK" not in r.stderr
    assert r.stdout.splitlines() == ["a", "7"]


def test_user_methods_on_str():
    src = 'impl str:\n    fn shout(self: str) -> string:\n        return self.to_upper() + "!"\n\nfn main():\n    print("hi".shout())\n'
    assert run_built(src).stdout.strip() == "HI!"


def test_unknown_str_method_lists_the_real_ones():
    _p, diags = front_end('fn main():\n    print("a".spilt(","))\n')
    assert diags[0].code == "GG0208"
    assert "split" in diags[0].hint
    assert diags[0].fixes and diags[0].fixes[0].edits[0].replacement == "split"
