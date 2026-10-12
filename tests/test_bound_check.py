"""A generic body is checked where it is declared, against its bounds (not only at each use)."""
from pathlib import Path

import pytest

from .helpers import messages

ROOT = Path(__file__).resolve().parents[1]


def has(msgs, text):
    return any(text in m for m in msgs)


def test_unused_generic_is_checked():
    msgs = messages("fn big[T](a: T, b: T) -> bool:\n    return a > b\n\nfn main():\n    pass\n")
    assert has(msgs, "`>` only compares numbers and text, found `T`")


def test_feature_bound_gives_only_its_methods():
    src = ("feature Named:\n    fn name(self: Self) -> str\n\n"
           "fn shout[T: Named](x: T) -> str:\n    return x.title()\n\nfn main():\n    pass\n")
    assert has(messages(src), "has no method named `title`")
    ok = src.replace("x.title()", "x.name()")
    assert messages(ok) == []


def test_builtin_bound_is_checked_with_each_kind():
    src = "fn bump[T: Int](x: T) -> T:\n    return x + 300\n\nfn main():\n    pass\n"
    assert has(messages(src), "300 is too large for `i8`")
    assert messages(src.replace("300", "1")) == []


def test_bounded_bodies_pass():
    src = ("fn biggest[T: Ord](a: T, b: T) -> T:\n    if a > b:\n        return a\n    return b\n\n"
           "fn twice[T: Num](x: T) -> T:\n    return x + T(1)\n\n"
           "fn first[T](xs: read List[T]) -> T:\n    return xs[0].clone()\n\n"
           "fn same[K: Key](a: K, b: K) -> bool:\n    return a == b and hash(a) == hash(b)\n\n"
           "fn main():\n    print(biggest(1, 2), twice(2.5), same(\"a\", \"a\"))\n")
    assert messages(src) == []


def test_key_bound_accepts_types_with_hash_and_eq():
    src = ("struct P:\n    x: i32\n\nimpl P:\n    fn hash(self) -> u64:\n        return u64(self.x)\n\n"
           "    fn eq(self, other: P) -> bool:\n        return self.x == other.x\n\n"
           "fn same[K: Key](a: K, b: K) -> bool:\n    return a == b\n\n"
           "fn main():\n    print(same(P{ x: 1 }, P{ x: 1 }))\n")
    assert messages(src) == []
    bad = src.replace("    fn hash(self) -> u64:\n        return u64(self.x)\n\n", "")
    assert has(messages(bad), "does not satisfy `Key`")


def test_copy_bound():
    src = "fn two[T: Copy](x: T) -> (T, T):\n    return (x, x)\n\nfn main():\n    print(two(1))\n"
    assert messages(src) == []
    assert has(messages(src.replace("two(1)", "two(List[i32]())")), "does not satisfy `Copy`")


def test_std_generics_satisfy_their_bounds(monkeypatch):
    import greengold.generics as generics
    from greengold.cli import analyze
    monkeypatch.setattr(generics, "_in_std", lambda d: False)
    src = ROOT / "tests" / "_all_std.gg"
    mods = sorted(p.stem for p in (ROOT / "greengold" / "std").glob("*.gg"))
    src.write_text("".join(f"import std.{m}\n" for m in mods) + "\nfn main():\n    pass\n", encoding="utf-8")
    try:
        _p, _s, diags, _c = analyze([str(src)])
    finally:
        src.unlink()
    errors = [f"{d.filename}:{d.line}: {d.message}" for d in diags.items if d.severity == "error"]
    assert errors == []
