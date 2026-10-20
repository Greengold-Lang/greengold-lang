"""std.can: frames, lengths, the CAN CRC-15 (against a bit-by-bit Python reference), and J1939 identifiers.

Spec: 16
"""
from tests.helpers import run_gg_source


def crc15(bits):
    crc = 0
    for bit in bits:
        top = (crc >> 14) & 1
        crc = (crc << 1) & 0x7FFF
        if top ^ bit:
            crc ^= 0x4599
    return crc


def test_crc15_matches_the_bitwise_reference(tmp_path):
    data = [0xA5, 0x3C, 0x00, 0xFF, 0x12, 0x80]
    cases = [(data, 48), (data, 45), (data[:1], 8), (data[:2], 13)]
    calls = []
    want = []
    for d, n in cases:
        arr = ", ".join(str(x) for x in d)
        calls.append(f"    a{len(calls)}: [{len(d)}]u8 = [{arr}]\n    print(can.frame_crc15(a{len(calls)}[..], {n}))")
        bits = [(d[i // 8] >> (7 - i % 8)) & 1 for i in range(n)]
        want.append(str(crc15(bits)))
    r = run_gg_source(tmp_path, "import std.can\n\nfn main():\n" + "\n".join(calls) + "\n")
    assert r.returncode == 0, r.stderr
    assert r.stdout.split() == want


def test_frames_lengths_and_j1939(tmp_path):
    r = run_gg_source(tmp_path, """import std.can

fn main():
    d: [3]u8 = [1, 2, 3]
    f = can.CanFrame.data_frame(0x123, d[..])
    print(f.len, f.payload()[2], f.is_valid(), f.extended)
    print(can.dlc_for_length(8), can.dlc_for_length(12), can.dlc_for_length(64), can.length_for_dlc(9, true), can.length_for_dlc(9, false), can.length_for_dlc(15, true))
    print(can.j1939_id(3, 0xF004, 0))
    j = can.j1939_parse(0x0CF00400)
    print(j.priority, j.pgn, j.destination, j.source, j.is_pdu1)
    k = can.j1939_parse(can.j1939_id(6, 0xEA05, 0x17))
    print(k.priority, k.pgn, k.destination, k.source, k.is_pdu1)
    rf = can.CanFrame.remote_frame(0x7FF, false, 4)
    print(rf.remote, rf.len, rf.is_valid())
""")
    assert r.returncode == 0, r.stderr
    assert r.stdout.splitlines() == ["3 3 true false", "8 9 15 12 8 64", str(0x0CF00400), "3 61444 255 0 false",
                                     f"6 {0xEA00} 5 23 true", "true 4 true"]


def test_bad_frames_stop_the_program(tmp_path):
    r = run_gg_source(tmp_path, """import std.can

fn main():
    d: [1]u8 = [1]
    f = can.CanFrame.data_frame(0x800, d[..])
""")
    assert r.returncode != 0
