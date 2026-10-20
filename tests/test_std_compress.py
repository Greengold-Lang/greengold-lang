"""std.compress against Python's zlib and gzip, in both directions."""
import gzip
import random
import zlib

from tests.helpers import run_gg_source


def _blobs():
    rng = random.Random(77)
    words = ["alpha", "beta", "gamma", "delta", "epsilon", "zeta", "eta", "theta"]
    text = (" ".join(rng.choice(words) for _ in range(3000))).encode()
    return [b"", b"a", b"abc" * 200, bytes(rng.randrange(256) for _ in range(500)), text, bytes(range(256)) * 20,
            b"x" * 70000]


def test_inflate_reads_what_python_writes(tmp_path):
    blobs = _blobs()
    lines = ["import std.compress", "import std.encoding", "", "fn h(text: str) -> List[u8]:", "    return encoding.hex_decode(text).value_or_panic()", "",
             "fn main():"]
    want = []
    for b in blobs:
        for level in (1, 6, 9):
            z = zlib.compress(b, level)
            lines.append(f'    print(encoding.hex_encode(compress.zlib_decompress(h("{z.hex()}"), 1000000).value_or_panic()) == "{b.hex()}")')
            want.append("true")
        g = gzip.compress(b)
        lines.append(f'    print(encoding.hex_encode(compress.gzip_decompress(h("{g.hex()}"), 1000000).value_or_panic()) == "{b.hex()}")')
        want.append("true")
        raw = zlib.compress(b)[2:-4]
        lines.append(f'    print(encoding.hex_encode(compress.inflate(h("{raw.hex()}"), 1000000).value_or_panic()) == "{b.hex()}")')
        want.append("true")
    r = run_gg_source(tmp_path, "\n".join(lines) + "\n")
    assert r.returncode == 0, r.stderr
    assert r.stdout.splitlines() == want


def test_python_reads_what_deflate_writes(tmp_path):
    blobs = _blobs()
    lines = ["import std.compress", "import std.encoding", "", "fn h(text: str) -> List[u8]:", "    return encoding.hex_decode(text).value_or_panic()", "",
             "fn main():"]
    for b in blobs:
        for level in (0, 1, 6, 9):
            lines.append(f'    d = h("{b.hex()}")')
            lines.append(f"    print(encoding.hex_encode(compress.zlib_compress(d, {level})))")
        lines.append(f'    print(encoding.hex_encode(compress.gzip_compress(h("{b.hex()}"), 5)))')
    r = run_gg_source(tmp_path, "\n".join(lines) + "\n")
    assert r.returncode == 0, r.stderr
    out = r.stdout.splitlines()
    k = 0
    for b in blobs:
        for level in (0, 1, 6, 9):
            assert zlib.decompress(bytes.fromhex(out[k])) == b
            k += 1
        assert gzip.decompress(bytes.fromhex(out[k])) == b
        k += 1
    # the repeats are actually found
    text = _blobs()[4]
    assert len(bytes.fromhex(out[4 * 5 + 2])) < len(text) * 0.6


def test_bad_input_is_an_error(tmp_path):
    z = zlib.compress(b"hello hello hello hello")
    bad_sum = bytearray(z)
    bad_sum[-1] ^= 1
    r = run_gg_source(tmp_path, f"""import std.compress
import std.encoding

fn h(text: str) -> List[u8]:
    return encoding.hex_decode(text).value_or_panic()

fn main():
    print(compress.zlib_decompress(h("{bytes(bad_sum).hex()}"), 1000).is_err())
    print(compress.zlib_decompress(h("{z[:10].hex()}"), 1000).is_err())
    print(compress.zlib_decompress(h("{z.hex()}"), 5).is_err())
    print(compress.inflate(h("ffffffff"), 1000).is_err(), compress.gzip_decompress(h("00112233445566778899aabbccddeeff0011"), 100).is_err())
    print(compress.zlib_decompress(h("{z.hex()}"), 1000).is_ok())
""")
    assert r.returncode == 0, r.stderr
    assert r.stdout.splitlines() == ["true", "true", "true", "true true", "true"]
