"""std.regex: Pike VM matching, groups, lazy repeats, classes, anchors, word boundaries, replace, split."""
from tests.helpers import run_built

SRC = r"""
import std.regex

fn show(pat: str, text: str):
    match regex.compile(pat):
        Ok(r):
            match r.find(text):
                Valid(m): print(pat, "->", m.start, m.end, m.text(), m.group(1))
                None: print(pat, "-> none")
        Err(e): print(pat, "-> error", e)

fn main():
    show("(\\w+)@(\\w+)\\.com", "mail ada@example.com now")
    show("a+?", "aaa")
    show("a+", "baaac")
    show("^ab|cd$", "xxcd")
    show("colou?r", "my color")
    show("[^0-9 ]+", "12 ab3")
    show("\\d{2,3}", "a1234")
    show("x{2}", "x{2}")
    show("é.ü", "aé€üb")
    show("\\bcat\\b", "concat cat")
    show("(a|ab)(c|bcd)(d*)", "abcd")
    show("(a*)+b", "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaac")
    show("a(", "x")
    show("*a", "x")
    show("[z-a]", "x")
    match regex.compile("\\s*,\\s*"):
        Ok(sep): print(sep.split("a , b,c ,d"), sep.replace_all("1, 2,3", ";"))
        Err(e): print(e)
    match regex.compile("(\\d+)-(\\d+)"):
        Ok(d):
            print(d.replace_all("1-2 and 30-40", "$2..$1 $$"), d.find_all("1-2 x 3-4").len(), d.is_match("nope"))
            match d.find_from("1-2 x 3-4", 1):
                Valid(m): print(m.text(), m.group_start(2), d.group_count())
                None: print("none")
        Err(e): print(e)
"""

EXPECTED = [
    '(\\w+)@(\\w+)\\.com -> 5 20 ada@example.com Valid("ada")',
    'a+? -> 0 1 a None',
    'a+ -> 1 4 aaa None',
    '^ab|cd$ -> 2 4 cd None',
    'colou?r -> 3 8 color None',
    '[^0-9 ]+ -> 3 5 ab None',
    '\\d{2,3} -> 1 4 123 None',
    'x{2} -> none',
    'é.ü -> 1 8 é€ü None',
    '\\bcat\\b -> 7 10 cat None',
    '(a|ab)(c|bcd)(d*) -> 0 4 abcd Valid("a")',
    '(a*)+b -> none',
    'a( -> error missing `)` at byte 2',
    '*a -> error nothing to repeat at byte 0',
    '[z-a] -> error bad range in `[...]` at byte 4',
    '["a", "b", "c", "d"] 1;2;3',
    '2..1 $ and 40..30 $ 2 false',
    '3-4 Valid(8) 3',
]


def test_regex(monkeypatch):
    monkeypatch.setenv("GG_LEAKCHECK", "1")
    r = run_built(SRC)
    assert r.returncode == 0, r.stderr
    assert "LEAK" not in r.stderr
    assert r.stdout.splitlines() == EXPECTED


def test_regex_is_linear_on_a_pathological_pattern():
    src = """import std.regex

fn main():
    text = string.new()
    for _i in 0..3000:
        text.append_byte('a')
    match regex.compile("(a*)*(a|b)*c"):
        Ok(r): print(r.is_match(text.as_str()))
        Err(e): print(e)
"""
    r = run_built(src, release=True, timeout=20)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "false"
