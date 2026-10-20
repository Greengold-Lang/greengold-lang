"""std.audit: a hash-chained append-only log; tampering, removal and replacement are detected.

Spec: 16
"""
import hashlib
import hmac

from tests.helpers import run_gg_source

WRITE = r"""import std.audit
import std.fs

fn main():
    fs.write_text("log.audit", "").value_or_panic()
    log = audit.AuditLog.open("log.audit").value_or_panic()
    log.append_at("first\tentry", 1000).value_or_panic()
    log.append_at("second\nline", 2000).value_or_panic()
    print(log.head(), log.len())
"""


def run_gg(tmp_path, source):
    """Runs `source` with the log file names turned into paths inside tmp_path."""
    base = tmp_path.as_posix()
    return run_gg_source(tmp_path, source.replace('"log.audit"', f'"{base}/log.audit"').replace('"k.audit"', f'"{base}/k.audit"'))


def test_entries_are_chained_with_sha256(tmp_path):
    r = run_gg(tmp_path, WRITE)
    assert r.returncode == 0, r.stderr
    lines = (tmp_path / "log.audit").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    prev = "0" * 64
    for i, (line, ts, msg) in enumerate(zip(lines, (1000, 2000), ("first\\tentry", "second\\nline")), 1):
        seq, millis, p, m, h = line.split("\t")
        assert (seq, millis, p, m) == (str(i), str(ts), prev, msg)
        assert h == hashlib.sha256(f"{seq}\t{millis}\t{p}\t{m}".encode()).hexdigest()
        prev = h
    assert r.stdout.split()[0] == prev and r.stdout.split()[1] == "2"


def test_verify_finds_changes_removals_and_replacement(tmp_path):
    r = run_gg(tmp_path, WRITE)
    assert r.returncode == 0, r.stderr
    head = r.stdout.split()[0]
    path = tmp_path / "log.audit"
    good = path.read_text(encoding="utf-8")
    check = """import std.audit

fn main():
    r = audit.verify("log.audit")
    print(r.value_or(999))
    a = audit.verify_anchored("log.audit", 2, "HEAD")
    print(a.value_or(999))
"""
    out = run_gg(tmp_path, check.replace("HEAD", head))
    assert out.returncode == 0, out.stderr
    assert out.stdout.split() == ["2", "2"]
    path.write_text(good.replace("first", "FIRST", 1), encoding="utf-8")          # an entry was edited
    assert run_gg(tmp_path, check.replace("HEAD", head)).stdout.split() == ["999", "999"]
    lines = good.splitlines(keepends=True)
    path.write_text(lines[0], encoding="utf-8")                                    # the tail was cut off
    out = run_gg(tmp_path, check.replace("HEAD", head))
    assert out.stdout.split() == ["1", "999"]                                       # the chain is fine, the anchor is not
    path.write_text("".join(reversed(lines)), encoding="utf-8")                    # entries were swapped
    assert run_gg(tmp_path, check.replace("HEAD", head)).stdout.split()[0] == "999"


def test_reopening_continues_the_chain_and_refuses_a_damaged_log(tmp_path):
    assert run_gg(tmp_path, WRITE).returncode == 0
    more = """import std.audit

fn main():
    log = audit.AuditLog.open("log.audit").value_or_panic()
    print(log.len())
    log.append_at("third", 3000).value_or_panic()
    print(audit.verify("log.audit").value_or(999))
"""
    r = run_gg(tmp_path, more)
    assert r.stdout.split() == ["2", "3"], r.stderr
    path = tmp_path / "log.audit"
    path.write_text(path.read_text(encoding="utf-8").replace("second", "SECOND", 1), encoding="utf-8")
    bad = run_gg(tmp_path, more)
    assert bad.returncode != 0                                                      # open() returns Err, value_or_panic stops


def test_keyed_log_needs_the_key(tmp_path):
    r = run_gg(tmp_path, """import std.audit

fn main():
    log = audit.AuditLog.open_keyed("k.audit", "abcd".as_bytes()).value_or_panic()
    log.append_at("x", 5).value_or_panic()
""")
    assert r.returncode == 0, r.stderr
    line = (tmp_path / "k.audit").read_text(encoding="utf-8").rstrip("\n").split("\t")
    body = "\t".join(line[:4]).encode()
    assert line[4] == hmac.new(b"abcd", body, hashlib.sha256).hexdigest()
