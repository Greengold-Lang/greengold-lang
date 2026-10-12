"""List helper methods (`map`, `filter`, `sort`, ...), written in Greengold in core.gg."""
from pathlib import Path

from tests.helpers import front_end, messages, run_built

ROOT = Path(__file__).resolve().parents[1]


def test_list_helpers_run(monkeypatch):
    monkeypatch.setenv("GG_LEAKCHECK", "1")
    r = run_built((ROOT / "examples" / "list_helpers.gg").read_text(encoding="utf-8"))
    assert r.returncode == 0, r.stderr
    assert "LEAK" not in r.stderr
    assert r.stdout.splitlines() == [
        "[50, 30, 90, 10] [5, 3, 9]",
        "18 Valid(1) Valid(9) true Valid(1) false",
        "true true 3",
        "18 Valid(5) Valid(5) Valid(1)",
        "[1, 3, 5, 9]",
        "[9, 5, 3, 1]",
        "[P { x: 1 }, P { x: 2 }]",
        "Valid(0) Valid(40) Valid(19)",
        "44",
    ]


def test_sort_large_list_is_ordered():
    src = """\
fn main():
    xs = List[i64]()
    for i in 0..1000:
        xs.push((i * 7919) % 1009)
    xs.sort()
    ok = true
    for i in 1..xs.len:
        if xs[i - 1] > xs[i]:
            ok = false
    print(ok, xs.len)
"""
    r = run_built(src)
    assert r.stdout.strip() == "true 1000", r.stderr


def test_list_of_moved_values_is_rejected():
    _p, diags = front_end("fn main():\n    ss = List[string]()\n    print(ss.map(fn(v: i32) -> i32 => v))\n")
    assert [d.code for d in diags] == ["GG0327"]
    assert "for x in ss:" in diags[0].hint


def test_callback_parameter_type_is_explained():
    msgs = messages("fn main():\n    ys = List[i32]()\n    print(ys.map(fn(v: i64) -> i64 => v))\n")
    assert msgs == ["The callback of `map` takes `i64`, but the list holds `i32`."]


def test_sorting_a_fixed_list_names_the_variable():
    _p, diags = front_end("fn main():\n    fixed xs = List[i32]()\n    xs.sort()\n")
    assert [d.code for d in diags] == ["GG0310"]
    assert all("_list_" not in n.message for n in diags[0].notes)


def test_unknown_list_method_suggests_a_helper():
    _p, diags = front_end("fn main():\n    xs = List[i32]()\n    print(xs.mapp(1))\n")
    assert "map" in diags[0].hint
