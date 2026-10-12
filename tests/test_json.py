"""`to_json(x)`, `from_json[T](text)`, and `x.to_string()` for every printable type."""
from pathlib import Path

from tests.helpers import front_end, run_built, EXAMPLES_DIR

ROOT = Path(__file__).resolve().parents[1]


def test_json_round_trip_and_errors(monkeypatch):
    monkeypatch.setenv("GG_LEAKCHECK", "1")
    r = run_built((EXAMPLES_DIR / "json.gg").read_text(encoding="utf-8"))
    assert r.returncode == 0, r.stderr
    assert "LEAK" not in r.stderr
    assert r.stdout.splitlines() == [
        '{"title":"Hi\\n","tags":["a\\"b","é"],"at":{"x":1,"y":-2},"shapes":[{"Circle":1.5},{"Rect":[2,3]},"Empty"],'
        '"color":"Green","note":null,"pair":[7,true],"grid":[3,4]}',
        'true ["a"b", "é"] Point { x: 1, y: -2 }',
        "Ok(Point { x: 4, y: 5 })",
        'Err("missing field `y` at byte 8")',
        'Ok([1, 2, 300]) Err("integer out of range at byte 10")',
        "Ok(Color.Red) Ok(Shape.Rect(1, 2)) Ok(None)",
    ]


def test_malformed_json_reports_position(monkeypatch):
    monkeypatch.setenv("GG_LEAKCHECK", "1")
    src = """\
struct P:
    name: string
    n: List[i32]

fn main():
    print(from_json[P]("{\\"name\\": \\"x\\", \\"n\\": [1, 2,]}"))
    print(from_json[P]("{\\"name\\": \\"x\\", \\"n\\": []} trailing"))
    print(from_json[P]("{\\"name\\": \\"x\\", \\"name\\": \\"y\\", \\"n\\": []}"))
    print(from_json[i32]("1.5"), from_json[f64]("1e3"), from_json[bool]("nope"))
"""
    r = run_built(src)
    assert r.returncode == 0, r.stderr
    assert "LEAK" not in r.stderr
    lines = r.stdout.splitlines()
    assert lines[0].startswith('Err("expected a number')
    assert lines[1].startswith('Err("unexpected text after the value')
    assert lines[2].startswith('Err("field `name` appears twice')
    assert lines[3].startswith('Err("expected an integer') and "Ok(1000)" in lines[3]


def test_views_cannot_be_read_from_json():
    _p, diags = front_end("struct P:\n    name: str\n\nfn main():\n    print(from_json[P](\"{}\"))\n")
    assert any("cannot be read from JSON" in d.message for d in diags)


def test_to_string_on_any_printable_value(monkeypatch):
    monkeypatch.setenv("GG_LEAKCHECK", "1")
    src = 'struct P:\n    x: i32\n\nfn main():\n    p = P{ x: 1 }\n    n = 42\n    print(p.to_string(), n.to_string() + "!", [1, 2].to_string())\n'
    r = run_built(src)
    assert r.stdout.strip() == "P { x: 1 } 42! [1, 2]"
    assert "LEAK" not in r.stderr
