"""User destructors: `impl T: fn drop(self: lend Self)` runs once when the owner goes away."""
from .helpers import messages, run_built


def has(msgs, text):
    return any(text in m for m in msgs)


FD = (
    "struct Fd:\n"
    "    n: i32\n\n"
    "impl Fd:\n"
    "    fn drop(self: lend Self):\n"
    "        print(f\"close {self.n}\")\n\n"
)


def out(src):
    res = run_built(src)
    assert res.returncode == 0, res.stderr
    return res.stdout.split()


def test_drop_runs_at_scope_end_in_reverse_order():
    src = FD + "fn main():\n    a = Fd{ n: 1 }\n    b = Fd{ n: 2 }\n    print(\"body\")\n"
    assert out(src) == ["body", "close", "2", "close", "1"]


def test_drop_runs_once_after_move():
    src = FD + ("fn take(f: consume Fd):\n    print(\"took\")\n\n"
                "fn main():\n    a = Fd{ n: 1 }\n    take(a)\n    print(\"after\")\n")
    assert out(src) == ["took", "close", "1", "after"]


def test_drop_on_early_return_and_in_loop():
    src = FD + ("fn f(n: i32) -> i32:\n    a = Fd{ n: n }\n    if n > 0:\n        return n\n    return 0\n\n"
                "fn main():\n    f(5)\n    for i in 0..2:\n        t = Fd{ n: i }\n    print(\"end\")\n")
    assert out(src) == ["close", "5", "close", "0", "close", "1", "end"]


def test_drop_of_list_elements_generic_and_enum():
    src = FD + (
        "struct Box2[T]:\n    v: T\n\n"
        "impl Box2[T]:\n    fn drop(self: lend Self):\n        print(\"box2\")\n\n"
        "enum E:\n    A(i32)\n    B\n\n"
        "impl E:\n    fn drop(self: lend Self):\n        print(\"e\")\n\n"
        "fn main():\n    xs = List[Fd]()\n    xs.push(Fd{ n: 7 })\n    b = Box2[i32]{ v: 1 }\n"
        "    e = E.A(1)\n    print(\"end\")\n")
    assert out(src) == ["end", "e", "box2", "close", "7"]


def test_drop_type_is_moved_not_copied():
    src = FD + "fn main():\n    a = Fd{ n: 1 }\n    b = a\n    print(a.n)\n"
    assert has(messages(src), "moved")


def test_drop_cannot_be_called():
    src = FD + "fn main():\n    a = Fd{ n: 1 }\n    a.drop()\n"
    assert has(messages(src), "runs by itself")


def test_drop_type_cannot_be_cloned_without_own_clone():
    src = FD + "fn main():\n    a = Fd{ n: 1 }\n    b = a.clone()\n"
    assert has(messages(src), "has a destructor")
    ok = FD.replace("    fn drop", "    fn clone(self) -> Fd:\n        return Fd{ n: self.n + 10 }\n\n    fn drop") + (
        "fn main():\n    a = Fd{ n: 1 }\n    b = a.clone()\n    print(b.n)\n")
    assert out(ok) == ["11", "close", "11", "close", "1"]


def test_drop_signature_is_checked():
    src = "struct A:\n    n: i32\n\nimpl A:\n    fn drop(self):\n        pass\n\nfn main():\n    a = A{ n: 1 }\n"
    assert has(messages(src), "fn drop(self: lend Self)")


def test_match_consume_of_drop_enum_is_rejected():
    src = ("enum E:\n    A(i32)\n    B\n\nimpl E:\n    fn drop(self: lend Self):\n        pass\n\n"
           "fn main():\n    e = E.A(1)\n    match consume e:\n        A(n):\n            print(n)\n        B:\n            pass\n")
    assert has(messages(src), "cannot take `E` apart")
