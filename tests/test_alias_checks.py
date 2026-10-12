from .helpers import front_end, messages


def check(source: str) -> list[str]:
    return messages(source)


def check_full(source: str):
    return front_end(source)[1]


PREAMBLE = """
struct Point:
    x: i32
    y: i32

fn lend_and_read(p: lend Point, q: Point):
    p.x += q.x

fn lend_and_lend(p: lend Point, q: lend Point):
    p.x += q.x

fn lend_and_give(p: lend Point, q: consume Point):
    p.x += q.x

fn lend_field_read_struct(n: lend i32, p: Point):
    n += p.x

fn lend_and_num(p: lend Point, n: i32):
    p.x += n

fn lend_fields(x: lend i32, y: lend i32):
    x += y

impl Point:
    fn hit(self: lend Point, other: lend Point):
        self.x += other.x

    fn combine(self: lend Point, other: Point):
        self.x += other.x
"""


def test_alias_lend_read_struct():
    src = PREAMBLE + """
fn main():
    a = Point{ x: 1, y: 2 }
    lend_and_read(a, a)
"""
    errs = check(src)
    assert any("aliasing risk" in e for e in errs)


def test_alias_read_lend_struct():
    src = PREAMBLE + """
fn main():
    a = Point{ x: 1, y: 2 }
    lend_and_read(a, a)
"""
    # Parameter order mismatch or alias
    errs = check(src)
    assert len(errs) > 0


def test_alias_lend_field_read_struct():
    src = PREAMBLE + """
fn main():
    a = Point{ x: 1, y: 2 }
    lend_field_read_struct(a.x, a)
"""
    errs = check(src)
    assert any("aliasing risk" in e for e in errs)


def test_alias_lend_give():
    src = PREAMBLE + """
fn main():
    a = Point{ x: 1, y: 2 }
    lend_and_give(a, a)
"""
    errs = check(src)
    assert any("while being moved (`consume`)" in e for e in errs)


def test_alias_give_lend():
    src = PREAMBLE + """
fn swap(p: consume Point, q: lend Point):
    q.x = p.x

fn main():
    a = Point{ x: 1, y: 2 }
    swap(a, a)
"""
    errs = check(src)
    assert any("while being moved (`consume`)" in e for e in errs)


def test_alias_method_receiver_lend():
    src = PREAMBLE + """
fn main():
    a = Point{ x: 1, y: 2 }
    a.hit(a)
"""
    errs = check(src)
    assert any("multiple times in the same call" in e for e in errs)


def test_alias_method_receiver_read():
    src = PREAMBLE + """
fn main():
    a = Point{ x: 1, y: 2 }
    a.combine(a)
"""
    # receiver is lend, other is read
    errs = check(src)
    assert any("aliasing risk" in e for e in errs)


def test_alias_positive_distinct_fields():
    src = PREAMBLE + """
fn main():
    a = Point{ x: 1, y: 2 }
    lend_fields(a.x, a.y)
"""
    errs = check(src)
    assert errs == []


def test_alias_positive_literal():
    src = PREAMBLE + """
fn main():
    a = Point{ x: 1, y: 2 }
    lend_and_num(a, 5)
"""
    errs = check(src)
    assert errs == []


def test_alias_positive_primitive_expr():
    src = PREAMBLE + """
fn main():
    a = Point{ x: 1, y: 2 }
    lend_and_num(a, a.x + 1)
"""
    errs = check(src)
    assert errs == []


def test_alias_positive_primitive_field():
    src = PREAMBLE + """
fn main():
    a = Point{ x: 1, y: 2 }
    lend_and_num(a, a.x)
"""
    errs = check(src)
    assert errs == []


def test_alias_diagnostic_notes():
    src = PREAMBLE + """
fn main():
    a = Point{ x: 1, y: 2 }
    lend_and_read(a, a)
"""
    items = check_full(src)
    alias_diags = [d for d in items if "aliasing risk" in d.message]
    assert len(alias_diags) == 1
    d = alias_diags[0]
    assert d.hint is not None
    assert "copy" in d.hint
    assert len(d.notes) == 1
    assert "first access is here" in d.notes[0].text

