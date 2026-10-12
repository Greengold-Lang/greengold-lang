"""Memory layout control: `union`, `packed struct`, `align(N) struct`, and inline `asm`."""
import platform

import pytest

from .helpers import messages, run_built


def test_union_packed_align():
    src = """union Bits:
    f: f32
    u: u32

packed struct Header:
    tag: u8
    len: u32

align(64) struct Line:
    a: i32

fn main():
    x = Bits{ f: 1.0 }
    unsafe:
        print(x.u)
        x.u = 0
        print(x.f)
    print(size_of[Bits](), size_of[Header](), align_of[Header](), size_of[Line](), align_of[Line]())
    h = Header{ tag: 1, len: 70000 }
    print(h.tag, h.len)
    lines: [2]Line = [Line{ a: 1 }, Line{ a: 2 }]
    print(lines[1].a)
"""
    res = run_built(src)
    assert res.returncode == 0, res.stderr
    assert res.stdout.splitlines() == ["1065353216", "0", "4 5 1 64 64", "1 70000", "2"]


@pytest.mark.parametrize("src, text", [
    ("union B:\n    f: f32\n    u: u32\n\nfn main():\n    x = B{ f: 1.0, u: 2 }\n", "sets exactly one field"),
    ("union B:\n    f: f32\n    u: u32\n\nfn main():\n    x = B{ f: 1.0 }\n    print(x.u)\n", "needs `unsafe:`"),
    ("union B:\n    s: string\n\nfn main():\n    pass\n", "holds plain data"),
    ("union B:\n    f: f32\n\nfn main():\n    x = B{ f: 1.0 }\n    print(x)\n", "cannot"),
    ("align(3) struct S:\n    a: i32\n\nfn main():\n    pass\n", "power of two"),
])
def test_layout_errors(src, text):
    msgs = messages(src)
    assert any(text in m for m in msgs), msgs


@pytest.mark.skipif(platform.machine().lower() not in ("amd64", "x86_64"), reason="x86-64 assembly")
def test_inline_asm():
    src = ('fn main():\n    x: u64 = 41\n    unsafe:\n        asm("nop", "")\n'
           '        y = asm[u64]("lea 1($1), $0", "=r,r", x)\n        print(y)\n')
    res = run_built(src)
    assert res.returncode == 0, res.stderr
    assert res.stdout.split() == ["42"]
    assert any("unsafe" in m for m in messages('fn main():\n    asm("nop", "")\n'))
