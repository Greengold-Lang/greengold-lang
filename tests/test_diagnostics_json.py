"""gg check --json matches the diagnostics schema, and fixes are verified by rechecking."""
import json
import re
from pathlib import Path

import pytest

from greengold.cli import cmd_check, cmd_explain
from greengold.codes import BY_CODE, RULES, error_codes_markdown
from greengold.diagnostics import position
from tests.helpers import front_end, with_main
from tests.test_errors import CASES

ROOT = Path(__file__).resolve().parent.parent
SCHEMA = json.loads((ROOT / "docs" / "gg-diagnostics.schema.json").read_text(encoding="utf-8"))


def _type_ok(value, name: str) -> bool:
    if name == "object":
        return isinstance(value, dict)
    if name == "array":
        return isinstance(value, list)
    if name == "string":
        return isinstance(value, str)
    if name == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if name == "boolean":
        return isinstance(value, bool)
    if name == "null":
        return value is None
    return False


def _ref(schema, root):
    if "$ref" not in schema:
        return schema
    node = root
    for part in schema["$ref"][2:].split("/"):
        node = node[part]
    return node


def schema_errors(value, schema, root=None, path="$"):
    root = root or schema
    schema = _ref(schema, root)
    if "const" in schema and value != schema["const"]:
        return [f"{path}: expected {schema['const']!r}"]
    if "enum" in schema and value not in schema["enum"]:
        return [f"{path}: {value!r} not in {schema['enum']}"]
    types = schema.get("type")
    if isinstance(types, list):
        if not any(_type_ok(value, t) for t in types):
            return [f"{path}: type {types}"]
        if value is None:
            return []
    elif types and not _type_ok(value, types):
        return [f"{path}: type {types}"]
    errors = []
    if isinstance(value, str) and "pattern" in schema and re.search(schema["pattern"], value) is None:
        errors.append(f"{path}: does not match {schema['pattern']}")
    if isinstance(value, int) and not isinstance(value, bool) and "minimum" in schema and value < schema["minimum"]:
        errors.append(f"{path}: below {schema['minimum']}")
    if isinstance(value, dict) and (types == "object" or "properties" in schema):
        props = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            extra = set(value) - set(props)
            if extra:
                errors.append(f"{path}: extra {sorted(extra)}")
        for key in schema.get("required", []):
            if key not in value:
                errors.append(f"{path}: missing {key}")
        for key, sub in props.items():
            if key in value:
                errors += schema_errors(value[key], sub, root, f"{path}.{key}")
    if isinstance(value, list) and "items" in schema:
        for i, item in enumerate(value):
            errors += schema_errors(item, schema["items"], root, f"{path}[{i}]")
    return errors


def check(tmp_path: Path, src: str) -> tuple[int, dict]:
    path = tmp_path / "main.gg"
    path.write_text(src, encoding="utf-8")
    import contextlib
    import io
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = cmd_check([str(path)], True)
    return code, json.loads(buf.getvalue())


def test_position_counts_unicode_columns_and_utf8_bytes():
    assert position("ğ", 1, 1) == {"line": 1, "column": 1, "offset": 0}
    assert position("ğ", 1, 2) == {"line": 1, "column": 2, "offset": 2}


def test_error_codes_document_matches_catalog():
    text = (ROOT / "docs" / "ERROR_CODES.md").read_text(encoding="utf-8")
    assert text == error_codes_markdown()
    assert len(BY_CODE) == len(RULES)
    for rule in RULES.values():
        assert rule.code in text
        assert rule.slug in text


def test_known_errors_have_real_codes():
    for _name, src, _expected in CASES:
        _prog, diags = front_end(src)
        assert diags, _name
        for diag in diags:
            assert diag.code != "GG0499", ( _name, diag.message)
            assert diag.code in BY_CODE


def test_check_json_matches_schema(tmp_path):
    code, doc = check(tmp_path, "fn main():\n    fixed x = 5\n    x = 6\n")
    assert code == 1
    assert schema_errors(doc, SCHEMA) == []
    assert doc["ok"] is False
    assert doc["summary"]["errors"] >= 1
    diag = doc["diagnostics"][0]
    assert diag["code"] == "GG0309"
    assert diag["fixes"][0]["applicability"] == "likely"
    assert diag["fixes"][0]["verified"] is True


def test_use_after_consume_labels_and_verified_fix(tmp_path):
    src = """struct Counter:
    value: i32

fn finish(c: consume Counter):
    print(c.value)

fn main():
    c = Counter{ value: 1 }
    finish(c)
    print(c.value)
"""
    code, doc = check(tmp_path, src)
    assert code == 1
    assert schema_errors(doc, SCHEMA) == []
    diag = next(d for d in doc["diagnostics"] if d["code"] == "GG0301")
    roles = {label["role"] for label in diag["labels"]}
    assert {"cause", "definition", "expected"} <= roles
    assert diag["details"]["callee"] == "finish"
    assert diag["details"]["parameter"] == "c"
    assert diag["details"]["state"] == "consumed"
    fix = diag["fixes"][0]
    assert fix["applicability"] == "likely"
    assert fix["verified"] is True
    assert fix["edits"][0]["replacement"] == ""


def test_tab_fix_is_safe_and_verified(tmp_path):
    _code, doc = check(tmp_path, "fn main():\n\tprint(1)\n")
    assert schema_errors(doc, SCHEMA) == []
    diag = doc["diagnostics"][0]
    assert diag["code"] == "GG0101"
    assert diag["fixes"][0]["applicability"] == "safe"
    assert diag["fixes"][0]["verified"] is True


def test_else_if_fix_is_safe_and_verified(tmp_path):
    src = "fn main():\n    if true:\n        print(1)\n    else if false:\n        print(2)\n"
    _code, doc = check(tmp_path, src)
    assert schema_errors(doc, SCHEMA) == []
    diag = next(d for d in doc["diagnostics"] if d["code"] == "GG0119")
    assert diag["fixes"][0]["verified"] is True
    assert diag["fixes"][0]["edits"][0]["replacement"] == "elif"


def test_same_line_syntax_is_suppressed(tmp_path):
    _code, doc = check(tmp_path, "fn main():\n\t    print(1)\n")
    assert schema_errors(doc, SCHEMA) == []
    assert doc["summary"]["suppressed"] >= 1
    assert doc["summary"]["errors"] == len(doc["diagnostics"])
    assert all(d["caused_by"] is None for d in doc["diagnostics"])


def test_explain_text_and_json(capsys):
    assert cmd_explain("GG0301", False) == 0
    out = capsys.readouterr().out
    assert "use-after-consume" in out
    assert "consume" in out
    assert cmd_explain("gg0301", True) == 0
    body = json.loads(capsys.readouterr().out)
    assert body["code"] == "GG0301"
    assert "callee" in body["details"]
    assert cmd_explain("GG9999", False) == 1


def test_human_render_comes_from_the_diagnostic(tmp_path, capsys):
    path = tmp_path / "main.gg"
    path.write_text(with_main("c = Counter{ value: 1 }\nfinish(c)\nshow(c)"), encoding="utf-8")
    import contextlib
    err = io_err = __import__("io").StringIO()
    with contextlib.redirect_stderr(err):
        assert cmd_check([str(path)], False) == 1
    text = err.getvalue()
    assert "Error:" in text
    assert "GG0301" in text
    assert "^" in text
    assert "help:" in text or "fix (" in text
    assert "finish(c)" in text
    assert capsys.readouterr().out == ""
