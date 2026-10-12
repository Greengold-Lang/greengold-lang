"""Parameter mode inference: a heap-owning parameter written without a mode gets `read`, `lend`, or `consume`
from what its body does with it."""
from greengold.cli import compile_to_ir
from tests.helpers import messages, run_built

BAG = "struct Bag:\n    items: List[i32]\n\n"


def test_mutated_heap_param_is_inferred_lend():
    src = "fn add(xs: List[i32]):\n    xs.push(1)\n\nfn main():\n    v = List[i32]()\n    add(v)\n    add(v)\n    print(v.len)\n"
    assert messages(src) == []
    r = run_built(src)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "2"


def test_moved_heap_param_is_inferred_consume():
    src = BAG + ("fn wrap(xs: List[i32]) -> Bag:\n    return Bag{ items: xs }\n\n"
                 "fn main():\n    v = List[i32]()\n    v.push(4)\n    b = wrap(v)\n    print(b.items.len)\n")
    r = run_built(src)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "1"


def test_inferred_consume_moves_the_argument():
    src = BAG + ("fn wrap(xs: List[i32]) -> Bag:\n    return Bag{ items: xs }\n\n"
                 "fn main():\n    v = List[i32]()\n    b = wrap(v)\n    print(v.len)\n")
    assert any("was moved" in m for m in messages(src))


def test_read_only_heap_param_stays_read():
    src = ("fn total(xs: List[i32]) -> i32:\n    t = 0\n    for x in xs:\n        t += x\n    return t\n\n"
           "fn main():\n    v = List[i32]()\n    print(total(v), total(v))\n")
    assert messages(src) == []
    sig = next(l for l in compile_to_ir(src).splitlines() if l.startswith('define internal i32 @"gg_total"'))
    assert "* nonnull" in sig and "noalias" not in sig  # by pointer, shared


def test_inference_is_transitive():
    src = ("fn add(xs: List[i32]):\n    xs.push(1)\n\nfn add2(ys: List[i32]):\n    add(ys)\n    add(ys)\n\n"
           "fn main():\n    v = List[i32]()\n    add2(v)\n    print(v.len)\n")
    r = run_built(src)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "2"


def test_inference_applies_to_self():
    src = ("struct S:\n    xs: List[i32]\n\nimpl S:\n    fn add(self: Self, x: i32):\n        self.xs.push(x)\n\n"
           "fn main():\n    s = S{ xs: List[i32]() }\n    s.add(3)\n    s.add(4)\n    print(s.xs.len)\n")
    r = run_built(src)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "2"


def test_immutable_argument_error_explains_inferred_lend():
    from tests.helpers import front_end
    src = "fn add(xs: List[i32]):\n    xs.push(1)\n\nfn main():\n    fixed v = List[i32]()\n    add(v)\n"
    diags = front_end(src)[1]
    assert diags and "cannot be `lend`ed" in diags[0].message
    assert any("takes it as `lend` (inferred)" in n.text for n in diags[0].notes)


def test_copyable_param_is_not_inferred():
    src = ("struct P:\n    x: i32\n\nfn bump(p: P):\n    p.x += 1\n\n"
           "fn main():\n    p = P{ x: 1 }\n    bump(p)\n")
    assert any("value parameter" in m for m in messages(src))


def test_explicit_mode_is_not_changed():
    src = "fn add(xs: read List[i32]):\n    xs.push(1)\n\nfn main():\n    v = List[i32]()\n    add(v)\n"
    assert any("`read` parameter" in m for m in messages(src))
