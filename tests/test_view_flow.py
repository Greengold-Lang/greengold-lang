"""View-flow summaries: a callee that stores a view of one argument inside another ties them at the call."""
from .helpers import messages


def has(msgs, text):
    return any(text in m for m in msgs)


KEEP = (
    "fn keep(out: lend List[str], s: read string):\n"
    "    out.push(s.as_str())\n\n"
)


def test_callee_storing_a_view_ties_the_arguments():
    src = KEEP + (
        "fn main():\n"
        "    names = List[str]()\n"
        "    s = string.from(\"x\")\n"
        "    keep(names, s)\n"
        "    s = string.from(\"y\")\n"
        "    print(names)\n")
    assert has(messages(src), "`names` is still tied to it")


def test_tie_ends_when_holder_is_not_used_again():
    src = KEEP + (
        "fn main():\n"
        "    names = List[str]()\n"
        "    s = string.from(\"x\")\n"
        "    keep(names, s)\n"
        "    print(names)\n"
        "    s = string.from(\"y\")\n"
        "    print(s)\n")
    assert messages(src) == []


def test_callee_that_copies_does_not_tie():
    src = (
        "fn keep(out: lend List[string], s: read string):\n"
        "    out.push(s.clone())\n\n"
        "fn main():\n"
        "    names = List[string]()\n"
        "    s = string.from(\"x\")\n"
        "    keep(names, s)\n"
        "    s = string.from(\"y\")\n"
        "    print(names)\n")
    assert messages(src) == []


def test_summary_is_transitive():
    src = KEEP + (
        "fn keep_twice(out: lend List[str], s: read string):\n"
        "    keep(out, s)\n\n"
        "fn main():\n"
        "    names = List[str]()\n"
        "    s = string.from(\"x\")\n"
        "    keep_twice(names, s)\n"
        "    s = string.from(\"y\")\n"
        "    print(names)\n")
    assert has(messages(src), "`names` is still tied to it")


def test_method_receiver_summary():
    src = (
        "struct Bag:\n"
        "    items: List[str]\n\n"
        "impl Bag:\n"
        "    fn add(self: lend Self, s: read string):\n"
        "        self.items.push(s.as_str())\n\n"
        "fn main():\n"
        "    b = Bag{ items: List[str]() }\n"
        "    s = string.from(\"x\")\n"
        "    b.add(s)\n"
        "    s = string.from(\"y\")\n"
        "    print(b.items)\n")
    assert has(messages(src), "`b` is still tied to it")
