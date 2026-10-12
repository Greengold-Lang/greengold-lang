"""`Shared[T]`: a reference-counted, read-only heap value."""
from pathlib import Path

from tests.helpers import messages, run_built, EXAMPLES_DIR

ROOT = Path(__file__).resolve().parents[1]


def test_shared_example_counts_owners_and_frees_once(monkeypatch):
    monkeypatch.setenv("GG_LEAKCHECK", "1")
    r = run_built((EXAMPLES_DIR / "shared.gg").read_text(encoding="utf-8"))
    assert r.returncode == 0, r.stderr
    assert r.stdout.splitlines() == ["3 prod 30 30", "42 41"]
    assert "leak" not in r.stderr.lower()


def test_shared_value_is_read_only():
    assert any("is a `Shared` value, which is read-only" in m for m in messages(
        "fn main():\n    s = Shared[List[i32]](List[i32]())\n    s.value.push(1)\n"))
    assert any("is a `Shared` value, which is read-only" in m for m in messages(
        "fn main():\n    s = Shared[i32](1)\n    s.value = 2\n"))


def test_shared_value_cannot_be_moved_out():
    assert any("cannot be moved out of the `Shared` value" in m for m in messages(
        "fn main():\n    s = Shared[List[i32]](List[i32]())\n    x = s.value\n"))
