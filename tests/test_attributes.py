"""`@attribute` lines: declaration, checking, and the resolved list tools read."""
from greengold.attrs import export

from .helpers import front_end, messages

DECL = "attribute net(mode: ident, reliable: bool = false, n: int = 1) on fn\n"
MAIN = "\nfn main():\n    pass\n"


def errors(src: str) -> list[str]:
    return messages(src)


def test_declared_attribute_checks_and_resolves():
    program, diags = front_end(DECL + "@net(server, reliable=true)\nfn f():\n    pass\n" + MAIN)
    assert not diags
    (item,) = export(program)
    assert item["name"] == "f" and item["kind"] == "fn"
    assert item["attrs"] == [{"name": "net", "args": {"mode": "server", "reliable": True, "n": 1}}]


def test_attribute_on_method_field_and_struct():
    src = (
        "attribute tag(label: str = \"\")\n"
        "@tag(\"s\")\nstruct S:\n    @tag\n    x: i32\n\n"
        "impl S:\n    @tag(\"m\")\n    fn get(self) -> i32:\n        return self.x\n" + MAIN
    )
    program, diags = front_end(src)
    assert not diags
    got = {(i["kind"], i["name"]): i["attrs"][0]["args"]["label"] for i in export(program)}
    assert got == {("struct", "S"): "s", ("field", "x"): "", ("fn", "get"): "m"}


def test_undeclared_attribute_is_an_error_with_a_suggestion():
    src = DECL + "@nett(server)\nfn f():\n    pass\n" + MAIN
    _prog, diags = front_end(src)
    assert [d.rule for d in diags] == ["unknown-attribute"]
    assert "`@net`" in diags[0].hint


def test_argument_problems():
    base = DECL + "{}\nfn f():\n    pass\n" + MAIN
    assert "needs the argument `mode`" in errors(base.format("@net"))[0]
    assert "must be an integer" in errors(base.format("@net(server, n=\"x\")"))[0]
    assert "no parameter `m`" in errors(base.format("@net(server, m=1)"))[0]
    assert "one too many" in errors(base.format("@net(server, true, 2, 3)"))[0]
    assert "given twice" in errors(base.format("@net(server, mode=client)"))[0]


def test_wrong_target_and_duplicate_use():
    assert "not on a struct" in errors(DECL + "@net(server)\nstruct S:\n    x: i32\n" + MAIN)[0]
    assert "written twice" in errors(DECL + "@net(server)\n@net(client)\nfn f():\n    pass\n" + MAIN)[0]


def test_attribute_declared_twice():
    assert "declared twice" in errors(DECL + DECL + MAIN)[0]


def test_attribute_above_something_else_is_rejected():
    src = DECL + "@net(server)\nconst X = 1\n" + MAIN
    _prog, diags = front_end(src)
    assert diags and "goes on a `fn`" in diags[0].message


def test_attributes_do_not_change_the_program():
    plain = front_end("fn f():\n    pass\n" + MAIN)[1]
    marked = front_end(DECL + "@net(server)\nfn f():\n    pass\n" + MAIN)[1]
    assert plain == [] and marked == []
