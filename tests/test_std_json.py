"""std.json: parse into a value tree, read it, build one, and write compact or indented text."""
from tests.helpers import run_built

SRC = r"""
import std.json

struct Wrap:
    id: i32
    data: json.Json

fn main():
    match json.parse("{\"user\": {\"name\": \"Ada\", \"age\": 36, \"tags\": [\"x\", true, null, 1.5e2]}, \"n\": -3}"):
        Ok(doc):
            u = doc.get("user")
            print(u.get("name").as_str_or("?"), u.get("age").as_i64(), u.get("tags").len(), u.get("tags").at(3).as_f64())
            print(doc.get("missing").is_null(), doc.has("n"), doc.keys(), doc.get("n").as_i64())
            print(doc.to_text())
        Err(e): print(e)
    print(json.parse("[1, 2,]"), json.parse("{\"a\" 1}"))
    out = json.object()
    out.set("ok", json.Json.Bool(true))
    out.set("name", json.text("a\"b"))
    list = json.array()
    list.push(json.Json.Num(1.0))
    list.push(json.object())
    out.set("items", list)
    out.set("ok", json.Json.Null)
    print(out.to_text())
    print(out.to_pretty())
    print(to_json(Wrap{ id: 7, data: out }))
"""


def test_json_value_tree(monkeypatch):
    monkeypatch.setenv("GG_LEAKCHECK", "1")
    r = run_built(SRC)
    assert r.returncode == 0, r.stderr
    assert "LEAK" not in r.stderr
    lines = r.stdout.splitlines()
    assert lines[:5] == [
        "Ada Valid(36) 4 Valid(150)",
        'true true ["user", "n"] Valid(-3)',
        '{"user":{"name":"Ada","age":36,"tags":["x",true,null,150]},"n":-3}',
        'Err("expected a value at byte 6") Err("expected `:` at byte 5")',
        '{"ok":null,"name":"a\\"b","items":[1,{}]}',
    ]
    assert lines[5:12] == ["{", '  "ok": null,', '  "name": "a\\"b",', '  "items": [', "    1,", "    {}", "  ]"]
    assert lines[-1] == '{"id":7,"data":{"ok":null,"name":"a\\"b","items":[1,{}]}}'
