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
        '{"user":{"name":"Ada","age":36,"tags":["x",true,null,1.5e2]},"n":-3}',
        'Err("expected a value at byte 6") Err("expected `:` at byte 5")',
        '{"ok":null,"name":"a\\"b","items":[1,{}]}',
    ]
    assert lines[5:12] == ["{", '  "ok": null,', '  "name": "a\\"b",', '  "items": [', "    1,", "    {}", "  ]"]
    assert lines[-1] == '{"id":7,"data":{"ok":null,"name":"a\\"b","items":[1,{}]}}'


def test_json_numbers_keep_their_exactness(tmp_path):
    from tests.helpers import run_gg_source
    r = run_gg_source(tmp_path, '''import std.json

fn main():
    doc = json.parse("{\\"id\\": 9007199254740993, \\"big\\": 123456789012345678901234567890, \\"price\\": 19.99, \\"amount\\": 12345.678901234567, \\"n\\": -7, \\"x\\": 1.5e3, \\"z\\": 0}").value_or_panic()
    print(doc.get("id").as_i64().value_or(0), doc.get("big").number_text().value_or(""), doc.get("price").as_f64().value_or(0.0))
    print(doc.get("amount").number_text().value_or(""), doc.get("n").as_i64().value_or(0), doc.get("x").as_f64().value_or(0.0), doc.get("z").as_i64().value_or(5))
    print(doc.to_text())
    n = json.number_from_text("0.10")
    print(n.number_text().value_or("?"), json.number_from_text("abc").is_null())
''')
    assert r.returncode == 0, r.stderr
    assert r.stdout.splitlines() == [
        "9007199254740993 123456789012345678901234567890 19.99",
        "12345.678901234567 -7 1500 0",
        '{"id":9007199254740993,"big":123456789012345678901234567890,"price":19.99,"amount":12345.678901234567,"n":-7,"x":1.5e3,"z":0}',
        "0.10 true",
    ]
