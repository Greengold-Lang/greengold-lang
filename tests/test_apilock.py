"""`gg api --lock` / `--check`: inferred parameter modes are part of the public API and stay stable."""
import json
import os

import pytest

from greengold import apilock
from greengold.cli import main

V1 = """struct Point:
    x: i32
    y: i32

enum Shape:
    Dot(Point)
    Empty

fn total(xs: List[i32]) -> i32:
    t = 0
    for x in xs:
        t += x
    return t

fn take(xs: consume List[i32]):
    print(xs.len)
"""


@pytest.fixture
def pkg(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "gg.toml").write_text('[package]\nname = "geo"\nversion = "1.2.0"\n', encoding="utf-8")
    (tmp_path / "src" / "shapes.gg").write_text(V1, encoding="utf-8")
    old = os.getcwd()
    os.chdir(tmp_path)
    try:
        assert main(["api", "--lock"]) == 0
        yield tmp_path
    finally:
        os.chdir(old)


def edit(pkg, old, new):
    p = pkg / "src" / "shapes.gg"
    p.write_text(p.read_text(encoding="utf-8").replace(old, new), encoding="utf-8")


def changes(pkg):
    found, _locked = apilock.check_lock(pkg, "1.2.0")
    return found


def test_lock_records_inferred_modes(pkg):
    doc = json.loads((pkg / "gg.api.lock").read_text(encoding="utf-8"))
    total = doc["symbols"]["shapes.total"]
    assert total["params"] == [{"name": "xs", "type": "List[i32]", "mode": "read"}]
    assert doc["symbols"]["shapes.take"]["params"][0]["mode"] == "consume"
    assert main(["api", "--check"]) == 0


def test_body_change_that_changes_a_mode_is_breaking(pkg, capsys):
    edit(pkg, "    return t\n", "    xs.push(t)\n    return t\n")
    found = changes(pkg)
    assert [c.breaking for c in found] == [True]
    assert "now `lend` (was `read`)" in found[0].message
    assert main(["api", "--check"]) == 1
    assert "Raise the version in gg.toml to 2.0.0" in capsys.readouterr().out


def test_asking_less_of_callers_is_compatible(pkg):
    edit(pkg, "fn take(xs: consume List[i32]):", "fn take(xs: List[i32]):")
    found = changes(pkg)
    assert found and not any(c.breaking for c in found)


def test_new_variant_and_new_field_are_breaking_new_function_is_not(pkg):
    edit(pkg, "    Empty\n", "    Empty\n    Line(Point, Point)\n")
    edit(pkg, "    y: i32\n", "    y: i32\n    z: i32\n")
    edit(pkg, "fn take(", "fn extra() -> i32:\n    return 1\n\nfn take(")
    found = {c.message.split("`")[1]: c.breaking for c in changes(pkg)}
    assert found == {"shapes.Shape": True, "shapes.Point": True, "shapes.extra": False}


def test_major_version_allows_the_break(pkg):
    edit(pkg, "    return t\n", "    xs.push(t)\n    return t\n")
    (pkg / "gg.toml").write_text('[package]\nname = "geo"\nversion = "2.0.0"\n', encoding="utf-8")
    assert main(["api", "--check"]) == 0


@pytest.mark.parametrize("locked, now, ok", [
    ("1.2.0", "1.3.0", False), ("1.2.0", "2.0.0", True), ("0.3.1", "0.4.0", True), ("0.3.1", "0.3.2", False),
])
def test_semver_rule(locked, now, ok):
    assert apilock.allows_breaking(locked, now) is ok
