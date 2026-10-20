"""std.fix: FIX frames are built and checked the way a counterparty does (BodyLength, CheckSum, field syntax).

Spec: 16
"""
from tests.helpers import run_gg_source

SOH = "\x01"


def fix_frame(begin, fields):
    body = "".join(f"{t}={v}{SOH}" for t, v in fields)
    head = f"8={begin}{SOH}9={len(body)}{SOH}"
    total = sum((head + body).encode()) % 256
    return f"{head}{body}10={total:03d}{SOH}"


def gg_str(s):
    return '"' + s.replace("\x01", "\x01") + '"'


def test_builder_matches_an_independent_frame(tmp_path):
    r = run_gg_source(tmp_path, """import std.fix { FixBuilder }
import std.fix

fn main():
    b = FixBuilder.new("FIX.4.4")
    b.add(35, "D")
    b.add(55, "EURUSD")
    b.add(38, "1000000")
    w = b.finish()
    print(w.as_str().len)
    m = fix.parse(w.as_str()).value_or_panic()
    print(m.get(55).value_or("?"), m.get_i64(38).value_or(-1), m.len())
    for i in 0..w.len:
        print(i32(w.as_str().as_bytes()[usize(i)]))
""")
    assert r.returncode == 0, r.stderr
    want = fix_frame("FIX.4.4", [(35, "D"), (55, "EURUSD"), (38, "1000000")])
    lines = r.stdout.splitlines()
    assert lines[0] == str(len(want))
    assert lines[1] == "EURUSD 1000000 6"
    assert bytes(int(x) for x in lines[2:]) == want.encode()


def test_parse_rejects_damaged_frames(tmp_path):
    good = fix_frame("FIX.4.2", [(35, "0"), (49, "A"), (56, "B")])
    cases = {
        "checksum": good[:-4] + "000" + SOH if not good.endswith("000" + SOH) else good[:-4] + "001" + SOH,
        "bodylength": good.replace("9=", "9=1", 1),
        "no_equals": fix_frame("FIX.4.2", [(35, "0")]).replace("35=0", "350"),
        "trailing": good + "x",
        "empty_value": fix_frame("FIX.4.2", [(35, "")]),
        "bad_tag": fix_frame("FIX.4.2", [(0, "x")]),
        "cut": good[:-5],
    }
    calls = "\n".join(f'    print(fix.parse({gg_str(v)}).is_ok())' for v in cases.values())
    ok = run_gg_source(tmp_path, f"""import std.fix

fn main():
    print(fix.parse({gg_str(good)}).is_ok())
{calls}
""")
    assert ok.returncode == 0, ok.stderr
    assert ok.stdout.split() == ["true"] + ["false"] * len(cases)


def test_repeating_group_values_keep_their_order(tmp_path):
    frame = fix_frame("FIX.4.4", [(35, "W"), (268, "2"), (269, "0"), (270, "1.1"), (269, "1"), (270, "1.2")])
    r = run_gg_source(tmp_path, f"""import std.fix

fn main():
    m = fix.parse({gg_str(frame)}).value_or_panic()
    all = m.get_all(269)
    print(all.len, all[0].as_str(), all[1].as_str(), m.get(999).has_value())
""")
    assert r.returncode == 0, r.stderr
    assert r.stdout.split() == ["2", "0", "1", "false"]
