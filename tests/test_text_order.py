"""`<`, `<=`, `>`, `>=` on `str` and `string`, and `Ord` for text."""
from tests.helpers import run_built

SRC = """fn biggest[T: Ord](xs: List[T]) -> T:
    best = xs[0]
    for x in xs:
        if x > best:
            best = x
    return best

fn main():
    a = string.from("apple")
    b = string.from("apples")
    print("a" < "b", "b" < "a", "ab" < "abc", "abc" <= "abc", "" < "a", a < b, b >= a, "Z" < "a", "b" > "abc")
    words = List[str]()
    for w in "pear fig apple figs".split(" "):
        words.push(w)
    words.sort()
    print(words, biggest(words), words.max())
"""


def test_text_orders_by_bytes_then_length(monkeypatch):
    monkeypatch.setenv("GG_LEAKCHECK", "1")
    r = run_built(SRC)
    assert r.returncode == 0, r.stderr
    assert "LEAK" not in r.stderr
    assert r.stdout.splitlines() == [
        "true false true true true true true true true",
        '["apple", "fig", "figs", "pear"] pear Valid("pear")',
    ]
