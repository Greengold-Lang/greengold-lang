"""std.encoding against Python's base64, binascii and zlib."""
import base64
import binascii
import random
import zlib

from tests.helpers import run_gg_source


def test_encoding_matches_python(tmp_path):
    rng = random.Random(5)
    blobs = [bytes(rng.randrange(256) for _ in range(n)) for n in (0, 1, 2, 3, 4, 5, 16, 31, 100)]
    lines = ["import std.encoding", "", "fn show(hex: str):",
             "    d = encoding.hex_decode(hex).value_or_panic()",
             "    b64 = encoding.base64_encode(d)",
             "    print(encoding.hex_encode(d), b64, encoding.base64url_encode(d), encoding.base32_encode(d))",
             "    print(encoding.base64_decode(b64.as_str()).value_or_panic().len, encoding.base32_decode(encoding.base32_encode(d).as_str()).value_or_panic().len)",
             "    print(encoding.crc32(d), encoding.crc32c(d), encoding.adler32(d), encoding.crc16_ccitt(d))", "", "fn main():"]
    want = []
    for b in blobs:
        lines.append(f'    show("{b.hex()}")')
        want.append(f"{b.hex()} {base64.b64encode(b).decode()} {base64.urlsafe_b64encode(b).decode().rstrip('=')} {base64.b32encode(b).decode()}".replace("  ", " "))
        want.append(f"{len(b)} {len(b)}")
        want.append(f"{zlib.crc32(b)} {_crc32c(b)} {zlib.adler32(b)} {binascii.crc_hqx(b, 0xFFFF)}")
    r = run_gg_source(tmp_path, "\n".join(lines) + "\n")
    assert r.returncode == 0, r.stderr
    got = r.stdout.splitlines()
    # an empty blob prints empty fields, which the shell of the test collapses the same way
    assert [" ".join(g.split()) for g in got] == [" ".join(w.split()) for w in want]


def _crc32c(data: bytes) -> int:
    crc = 0xFFFFFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ 0x82F63B78 if crc & 1 else crc >> 1
    return crc ^ 0xFFFFFFFF


def test_known_check_values(tmp_path):
    r = run_gg_source(tmp_path, """import std.encoding

fn main():
    d = "123456789".as_bytes()
    print(encoding.crc32(d), encoding.crc32c(d), encoding.crc16_modbus(d), encoding.crc16_ccitt(d), encoding.crc8(d))
    print(encoding.fletcher16("abcde".as_bytes()), encoding.base64_decode("a$").is_err(), encoding.hex_decode("abc").is_err())
""")
    assert r.returncode == 0, r.stderr
    assert r.stdout.splitlines() == ["3421780262 3808858755 19255 10673 244", "51440 true true"]
