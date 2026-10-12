"""Non-lexical borrows: a stored view holds its owner until its last use, through loops and branches."""
import pytest

from .helpers import messages


def check(body):
    return messages("fn main():\n" + "".join("    " + l + "\n" for l in body.splitlines()))


@pytest.mark.parametrize("body", [
    # the view is given a new value before it is used again
    's = string.from("a")\nt = s.as_str()\nprint(t)\nt = "lit"\ns = string.from("b")\nprint(t, s)',
    's = string.from("a")\nt = s.as_str()\ns = string.from("b")\nt = "lit"\nprint(t)',
    # each iteration takes a fresh view after the change
    's = string.from("a")\nt = "x"\nfor i in 0..3:\n    print(t)\n    s.append_str("z")\n    t = s.as_str()',
    's = string.from("a")\nfor i in 0..3:\n    t = s.as_str()\n    print(t)\n    s.append_str("z")',
    # the view is used only on the other branch
    's = string.from("a")\nt = s.as_str()\nif true:\n    s.append_str("x")\nelse:\n    print(t)',
])
def test_dead_views_do_not_hold_their_owner(body):
    assert check(body) == []


@pytest.mark.parametrize("body", [
    's = string.from("a")\nt = "x"\nfor i in 0..3:\n    s.append_str("z")\n    print(t)\n    t = s.as_str()',
    's = string.from("a")\nnames = List[str]()\nfor i in 0..3:\n    names.push(s.as_str())\n    s.append_str("z")\nprint(names)',
    's = string.from("a")\nt = s.as_str()\nwhile true:\n    s.append_str("x")\n    break\nprint(t)',
    's = string.from("a")\nt = s.as_str()\ndefer print(t)\ns.append_str("x")',
])
def test_live_views_hold_their_owner(body):
    assert any("still tied to it" in m for m in check(body)), check(body)
