"""std.csv, std.toml, std.uuid and std.log."""
import csv as pycsv
import io
import json
import re
import tomllib
import uuid as pyuuid

from tests.helpers import run_gg_source


def test_csv_matches_python(tmp_path):
    samples = ['a,b,c\n1,2,3\n', 'x,"y,z",w\n', '"multi\nline",2\n', '"say ""hi""",b\n', 'a,,c\n,,\n', 'one\r\ntwo\r\n', 'last,no newline']
    lines = ["import std.csv", "", "fn show(text: str):",
             "    rows = csv.parse(text, ',').value_or_panic()",
             "    print(rows.len)",
             "    for r in rows:",
             "        print(r.len, csv.format_row(r, '|'))", "", "fn main():"]
    want = []
    for s in samples:
        lines.append(f"    show({json.dumps(s)})")
        rows = list(pycsv.reader(io.StringIO(s, newline=""), delimiter=","))
        want.append(str(len(rows)))
        for r in rows:
            out = io.StringIO()
            pycsv.writer(out, delimiter="|", lineterminator="\n").writerow(r)
            want.append(f"{len(r)} {out.getvalue()[:-1]}")
    r = run_gg_source(tmp_path, "\n".join(lines) + "\n")
    assert r.returncode == 0, r.stderr
    assert r.stdout == "\n".join(want) + "\n"


TOML_DOC = '''title = "T \\u00e9"
count = 0x1F
neg = -17
big = 1_000
pi = 3.14
flag = false
lit = 'C:/path'
multi = """first
second"""
list = [1, 2, 3]
nested = [[1, 2], ["a"]]
dotted.key.here = "v"

[server]
port = 8080
hosts = ["a", "b",
  "c"]  # comment

[server.tls]
cert = "x.pem"

[[user]]
name = "ann"
[[user]]
name = "bob"
tags = {a = 1, b = "x"}
'''

TOML_PROGRAM = '''import std.toml

fn main():
    d = toml.parse(DOC).value_or_panic()
    print(d.to_text())
    print(toml.parse("a = 1\\na = 2\\n").is_err(), toml.parse("= 3").is_err(), toml.parse("x = \\"open").is_err(), toml.parse("[a]\\nb = 1\\n[a]\\nb = 2\\n").is_ok())
    again = toml.parse(toml.to_text(d).as_str()).value_or_panic()
    print(again.to_text() == d.to_text())
'''


def test_toml_matches_python(tmp_path):
    r = run_gg_source(tmp_path, TOML_PROGRAM.replace("DOC", json.dumps(TOML_DOC)))
    assert r.returncode == 0, r.stderr
    lines = r.stdout.splitlines()
    assert json.loads(lines[0]) == tomllib.loads(TOML_DOC)
    assert lines[1] == "true true true false"
    assert lines[2] == "true"


UUID_PROGRAM = '''import std.uuid
import std.log

fn main():
    a = uuid.v4()
    b = uuid.v7()
    print(a.version(), b.version(), a.to_string(), a.equals(a), a.equals(b), uuid.nil().is_nil())
    print(uuid.parse("7F3C2A1E-9b04-4c5d-8e21-3a6b0d9c4f12").value_or_panic().to_string(), uuid.parse("xyz").is_err())
    print(uuid.v5(uuid.namespace_dns(), "python.org".as_bytes()).to_string(), uuid.v7_at(1700000000123).unix_millis())
    log.info("started")
    log.debug("hidden")
    log.set_level(log.DEBUG)
    log.kv(log.ERROR, "failed", "status", "503")
    log.set_json(true)
    log.warn("quote \\" and newline")
    print(log.enabled(log.TRACE), log.enabled(log.INFO))
'''


def test_uuid_and_log(tmp_path):
    r = run_gg_source(tmp_path, UUID_PROGRAM)
    assert r.returncode == 0, r.stderr
    out = r.stdout.splitlines()
    first = out[0].split()
    assert first[0] == "4" and first[1] == "7" and pyuuid.UUID(first[2]).version == 4 and first[3:] == ["true", "false", "true"]
    assert out[1] == "7f3c2a1e-9b04-4c5d-8e21-3a6b0d9c4f12 true"
    assert out[2] == f"{pyuuid.uuid5(pyuuid.NAMESPACE_DNS, 'python.org')} 1700000000123"
    err = r.stderr.splitlines()
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT[\d:.]+Z INFO  started", err[0])
    assert err[1].endswith("ERROR failed status=503")
    assert json.loads(err[2])["msg"] == 'quote " and newline'
    assert out[3] == "false true"
