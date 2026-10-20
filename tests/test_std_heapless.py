"""std.heapless: fixed-capacity containers, and that they link for a bare-metal target with --no-std."""
import shutil
import subprocess
import sys

import pytest

from tests.helpers import ROOT, run_gg_source

PROGRAM = r'''import std.heapless { FixedVec, RingBuffer, FixedString, FixedMap, FixedBitSet }

fn main():
    v = FixedVec[i32, 4].new(0)
    print(v.push(10), v.push(20), v.push(30), v.push(40), v.push(50), v.is_full())
    print(v.insert(0, 5), v.pop().value_or(-1), v.remove(1).value_or(-1), v.len())
    s = v.as_slice()
    print(s.len, s[0], s[1])
    print(v.get(9).is_none(), v.swap_remove(0).value_or(-1), v.len())
    r = RingBuffer[u8, 3].new(0)
    r.push(1)
    r.push(2)
    r.push(3)
    print(r.push(4), r.push_overwrite(4), r.pop().value_or(0), r.get(1).value_or(0), r.peek().value_or(0), r.len())
    fs = FixedString[16].new()
    print(fs.push_str("abc"), fs.push_i64(-405), fs.push_str("0123456789ABC"), fs.len(), fs.as_str(), fs.equals("abc-405"))
    m = FixedMap[u32, f64, 2].new(0, 0.0)
    print(m.insert(7, 1.5), m.insert(9, 2.5), m.insert(11, 3.5), m.insert(7, 4.5), m.get(7).value_or(0.0), m.remove(9).value_or(0.0), m.len())
    b = FixedBitSet[2].new()
    b.insert(3)
    b.insert(70)
    print(b.contains(3), b.contains(4), b.count(), b.insert(500), b.next_from(4).value_or(0))
'''

NO_STD = r'''import std.heapless { FixedVec, RingBuffer, FixedString }
import std.bits
import std.math

fn main():
    v = FixedVec[i32, 8].new(0)
    r = RingBuffer[u8, 4].new(0)
    s = FixedString[32].new()
    for i in 0..8:
        v.push(i32(i) * 3)
        r.push_overwrite(u8(i))
        s.push_i64(i64(i))
    total = 0
    for i in 0..v.len():
        total += v.get(i).value_or(0)
    x = bits.popcount(u32(total)) + bits.leading_zeros(u8(r.peek().value_or(1)))
    process_exit_code(i32(x) + i32(s.len()) + i32(math.isqrt(u64(total))))

fn process_exit_code(c: i32):
    unsafe:
        asm_none(c)

fn asm_none(c: i32):
    pass
'''


def test_heapless_containers(tmp_path):
    r = run_gg_source(tmp_path, PROGRAM)
    assert r.returncode == 0, r.stderr
    assert r.stdout.splitlines() == [
        "true true true true false true",
        "false 40 20 2",
        "2 10 30",
        "true 10 1",
        "false true 2 4 3 2",
        "true true false 7 abc-405 true",
        "true true false true 4.5 2.5 1",
        "true false 2 false 70",
    ]


@pytest.mark.skipif(not (shutil.which("ld.lld") or shutil.which("zig")), reason="no linker for cortex-m4")
def test_heapless_links_without_libc_for_cortex_m4(tmp_path):
    src = tmp_path / "m4.gg"
    src.write_text(NO_STD, encoding="utf-8")
    out = tmp_path / "m4.elf"
    r = subprocess.run([sys.executable, "-m", "greengold", "build", str(src), "--no-std", "--target", "cortex-m4",
                        "-o", str(out)], capture_output=True, text=True, cwd=ROOT)
    assert r.returncode == 0, r.stdout + r.stderr
