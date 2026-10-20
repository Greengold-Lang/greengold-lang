"""std.packet: big endian signed/float, CRC trailers, bit fields."""
import struct
import zlib

from tests.helpers import run_gg_source


def test_big_endian_signed_float_and_crc(tmp_path):
    r = run_gg_source(tmp_path, """import std.packet
import std.encoding

fn main():
    w = packet.ByteWriter.new()
    w.put_i16_be(-2)
    w.put_i32_be(-100000)
    w.put_i64_be(-5)
    w.put_f32_be(1.5)
    w.put_f64_be(-2.25)
    w.put_crc16()
    print(encoding.hex_encode(w.as_str().as_bytes()))
    print(packet.check_crc16(w.as_str()))
    r = packet.ByteReader.new(w.as_str())
    print(r.get_i16_be().value_or(0), r.get_i32_be().value_or(0), r.get_i64_be().value_or(0), r.get_f32_be().value_or(0.0), r.get_f64_be().value_or(0.0))
    bad = string.from("x")
    bad.append_str(w.as_str())
    print(packet.check_crc16(bad.as_str()), packet.check_crc16("a"))
    v = packet.ByteWriter.new()
    v.put_u8(7)
    v.put_crc32()
    print(packet.check_crc32(v.as_str()), encoding.hex_encode(v.as_str().as_bytes()))
""")
    assert r.returncode == 0, r.stderr
    body = struct.pack(">hiqfd", -2, -100000, -5, 1.5, -2.25)
    import binascii
    crc = binascii.crc_hqx(body, 0xFFFF)
    lines = r.stdout.splitlines()
    assert lines[0] == (body + struct.pack(">H", crc)).hex()
    assert lines[1] == "true"
    assert lines[2] == "-2 -100000 -5 1.5 -2.25"
    assert lines[3] == "false false"
    assert lines[4] == "true " + (b"\x07" + struct.pack(">I", zlib.crc32(b"\x07"))).hex()


def test_bit_fields(tmp_path):
    r = run_gg_source(tmp_path, """import std.packet
import std.encoding

fn main():
    w = packet.BitWriter.new()
    w.put_bits(5, 3)
    w.put_bits(0x1FF, 9)
    w.put_bool(true)
    w.put_bits(0, 2)
    w.put_bits(0xABCDEF0123456789, 64)
    print(w.bit_len(), encoding.hex_encode(w.finish().as_bytes()))
    r = packet.BitReader.new(w.finish().as_str())
    print(r.get_bits(3).value_or(99), r.get_bits(9).value_or(99), r.get_bool().value_or(false), r.get_bits(2).value_or(99))
    print(r.get_bits(64).value_or(0), r.bits_left(), r.get_bits(9).is_err())
    n = packet.BitWriter.new()
    n.put_bits(0b1101, 4)
    n.put_bits(0b0110, 4)
    nr = packet.BitReader.new(n.finish().as_str())
    print(nr.get_signed(4).value_or(0), nr.get_signed(4).value_or(0))
""")
    assert r.returncode == 0, r.stderr
    bits = f"{5:03b}{0x1FF:09b}1{0:02b}{0xABCDEF0123456789:064b}"
    padded = bits + "0" * (-len(bits) % 8)
    data = int(padded, 2).to_bytes(len(padded) // 8, "big")
    lines = r.stdout.splitlines()
    assert lines[0] == f"{len(bits)} {data.hex()}"
    assert lines[1] == "5 511 true 0"
    assert lines[2] == f"{0xABCDEF0123456789} {len(padded) - len(bits) + 0} true"
    assert lines[3] == "-3 6"
