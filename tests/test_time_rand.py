"""std.time (monotonic clock, sleep, UTC dates, ISO 8601) and std.rand secure bytes; platform `if`s."""
from tests.helpers import run_built

SRC = """import std.time
import std.rand

fn main():
    t = time.Instant.now()
    time.sleep_millis(30)
    e = t.elapsed_millis()
    print(e >= 25 and e < 1000)
    print(time.datetime_from_unix_millis(0).to_iso(), time.datetime_from_unix_millis(951782400123).to_iso())
    print(time.datetime_from_unix_millis(-1).to_iso(), time.datetime_from_unix_millis(4102444799000).to_iso())
    d = time.parse_iso("2024-02-29T23:30:00.5+02:00")
    match d:
        Ok(x): print(x.to_iso(), x.weekday(), x.to_unix_millis())
        Err(m): print(m)
    print(time.parse_iso("2023-02-29"), time.parse_iso("2024-13-01T00:00:00Z"))
    now = time.now_utc()
    print(now.year >= 2024, time.unix_millis() / 1000 - time.current_time() <= 1)
    b = rand.secure_bytes(32)
    r = rand.rng_from_entropy()
    print(b.len, rand.secure_u64() != rand.secure_u64(), r.below(10) < 10)
"""


def test_time_and_secure_random(monkeypatch):
    monkeypatch.setenv("GG_LEAKCHECK", "1")
    r = run_built(SRC)
    assert r.returncode == 0, r.stderr
    assert "LEAK" not in r.stderr
    assert r.stdout.splitlines() == [
        "true",
        "1970-01-01T00:00:00Z 2000-02-29T00:00:00.123Z",
        "1969-12-31T23:59:59.999Z 2099-12-31T23:59:59Z",
        "2024-02-29T21:30:00.500Z 3 1709242200500",
        'Err("no such date") Err("no such date")',
        "true true",
        "32 true true",
    ]


def test_branch_for_another_platform_is_not_compiled():
    src = """weak extern "nowhere.h" fn only_on_plan9() -> i32

fn main():
    if target_os() == "plan9" and target_arch() != "nope":
        unsafe:
            print(only_on_plan9())
    elif not (target_os() != "plan9"):
        print("unreachable")
    else:
        print("here")
"""
    r = run_built(src)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "here"
