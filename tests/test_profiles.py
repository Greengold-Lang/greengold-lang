"""`gg check --profile safety`.

Spec: 18
"""
import json
import subprocess
import sys

from tests.helpers import ROOT

BAD = """static counter: u32 = 0

fn bad_unsafe():
    unsafe:
        counter = counter + 1

fn bad_panic(x: Optional[i32]) -> i32:
    return x.value_or_panic()

fn fact(n: u32) -> u32:
    if n <= 1:
        return 1
    return n * fact(n - 1)

fn heap() -> i32:
    xs = List[i32]()
    xs.push(1)
    return xs[0]

fn loops() -> i32:
    i = 0
    while i < 10:
        i += 1
    return i

@allow(unbounded_loop, heap)
fn excused() -> i32:
    xs = List[i32]()
    n = 0
    while n < 3:
        n += 1
    return n

fn good(a: [4]i32) -> i32:
    t = 0
    for i in 0..4:
        t += a[i]
    return t

fn main():
    print(good([1, 2, 3, 4]))
"""

GOOD = """fn good(a: [4]i32) -> i32:
    t = 0
    for i in 0..4:
        t += a[i]
    return t

fn main():
    print(good([1, 2, 3, 4]))
"""


def gg(*args):
    return subprocess.run([sys.executable, "-m", "greengold", *args], capture_output=True, text=True, cwd=ROOT)


def test_safety_profile_reports_each_rule(tmp_path):
    f = tmp_path / "bad.gg"
    f.write_text(BAD, encoding="utf-8")
    r = gg("check", str(f), "--profile", "safety", "--json")
    assert r.returncode == 1
    doc = json.loads(r.stdout)
    rules = sorted({d["rule"] for d in doc["diagnostics"]})
    assert rules == ["profile-heap", "profile-mutable-static", "profile-panic", "profile-recursion", "profile-unbounded-loop",
                     "profile-unsafe"]
    by_rule = {d["rule"]: d for d in doc["diagnostics"]}
    assert "bad_unsafe" in by_rule["profile-unsafe"]["message"]
    assert "fact" in by_rule["profile-recursion"]["message"]
    # the excused function is not reported, and `good` and `main` pass
    text = r.stdout
    assert "excused" not in text and "good" not in text.replace("good(a", "")


def test_plain_check_does_not_apply_the_profile(tmp_path):
    f = tmp_path / "bad.gg"
    f.write_text(BAD, encoding="utf-8")
    assert gg("check", str(f)).returncode == 0


def test_clean_program_passes_and_exceptions_are_listed(tmp_path):
    f = tmp_path / "good.gg"
    f.write_text(GOOD, encoding="utf-8")
    r = gg("check", str(f), "--profile", "safety")
    assert r.returncode == 0 and "ok" in r.stdout
    b = tmp_path / "bad.gg"
    b.write_text(BAD, encoding="utf-8")
    r2 = gg("check", str(b), "--profile", "safety", "--list-allowed", "--allow", "unsafe_code", "--allow", "panic",
            "--allow", "recursion", "--allow", "heap", "--allow", "unbounded_loop", "--allow", "mutable_static")
    assert r2.returncode == 0, r2.stdout + r2.stderr
    assert "excused allows unbounded_loop" in r2.stdout and "excused allows heap" in r2.stdout


def test_complexity_limit(tmp_path):
    f = tmp_path / "c.gg"
    branches = "".join(f"    if x == {i}:\n        t += {i}\n" for i in range(20))
    f.write_text(f"fn many(x: i32) -> i32:\n    t = 0\n{branches}    return t\n\nfn main():\n    print(many(3))\n", encoding="utf-8")
    r = gg("check", str(f), "--profile", "safety")
    assert r.returncode == 1 and "complexity 21" in (r.stdout + r.stderr)
    assert gg("check", str(f), "--profile", "safety", "--max-complexity", "30").returncode == 0
