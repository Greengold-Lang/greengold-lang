"""UTF-8 helpers on text: char_count, chars, char_at, char_len_at, is_utf8, push_char."""
from tests.helpers import run_built

SRC = """
fn main():
    t = "aé€😀"
    print(t.len, t.char_count(), t.chars(), t.char_at(1), t.char_len_at(3), t.is_utf8())
    s = string.new()
    for c in t.chars():
        s.push_char(c)
    s.push_char(0xD800)
    print(s, s.char_count(), s.as_str().is_utf8())
    bad = string.new()
    bad.append_byte(0xC0)
    bad.append_byte('A')
    bad.append_byte(0xE2)
    print(bad.as_str().is_utf8(), bad.as_str().chars(), bad.char_count())
"""


def test_utf8_helpers(monkeypatch):
    monkeypatch.setenv("GG_LEAKCHECK", "1")
    r = run_built(SRC)
    assert r.returncode == 0, r.stderr
    assert "LEAK" not in r.stderr
    assert r.stdout.splitlines() == [
        "10 4 [97, 233, 8364, 128512] 233 3 true",
        "aé€😀� 5 true",
        "false [65533, 65, 65533] 3",
    ]
