"""std.hash against Python's hashlib, hmac and the `cryptography` package."""
import hashlib
import hmac
import random

import pytest

from tests.helpers import run_gg_source


def _blobs():
    rng = random.Random(3)
    sizes = [0, 1, 3, 55, 56, 57, 63, 64, 65, 111, 112, 113, 127, 128, 129, 135, 136, 137, 200, 1000, 5000]
    return [bytes(rng.randrange(256) for _ in range(n)) for n in sizes]


def test_digests_match_hashlib(tmp_path):
    blobs = _blobs()
    lines = ["import std.hash", "import std.encoding", "", "fn show(hex: str):",
             "    d = encoding.hex_decode(hex).value_or_panic()",
             "    print(encoding.hex_encode(hash.sha256(d)))",
             "    print(encoding.hex_encode(hash.sha512(d)))",
             "    print(encoding.hex_encode(hash.sha384(d)))",
             "    print(encoding.hex_encode(hash.sha1(d)))",
             "    print(encoding.hex_encode(hash.sha3_256(d)))",
             "    print(encoding.hex_encode(hash.sha3_512(d)))",
             "    print(encoding.hex_encode(hash.shake128(d, 40)))",
             "    print(encoding.hex_encode(hash.shake256(d, 17)))",
             "    h = hash.sha256_new()",
             "    half = d.len / 2",
             "    h.update(d[0..half])",
             "    h.update(d[half..d.len])",
             "    print(encoding.hex_encode(h.finish()))", "", "fn main():"]
    want = []
    for b in blobs:
        lines.append(f'    show("{b.hex()}")')
        want += [hashlib.sha256(b).hexdigest(), hashlib.sha512(b).hexdigest(), hashlib.sha384(b).hexdigest(),
                 hashlib.sha1(b).hexdigest(), hashlib.sha3_256(b).hexdigest(), hashlib.sha3_512(b).hexdigest(),
                 hashlib.shake_128(b).hexdigest(40), hashlib.shake_256(b).hexdigest(17), hashlib.sha256(b).hexdigest()]
    r = run_gg_source(tmp_path, "\n".join(lines) + "\n")
    assert r.returncode == 0, r.stderr
    assert r.stdout.splitlines() == want


def test_hmac_hkdf_pbkdf2(tmp_path):
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    key, msg, longkey = b"key", b"The quick brown fox", bytes(range(200))
    src = f"""import std.hash
import std.encoding

fn h(text: str) -> List[u8]:
    return encoding.hex_decode(text).value_or_panic()

fn main():
    key = h("{key.hex()}")
    msg = h("{msg.hex()}")
    lk = h("{longkey.hex()}")
    print(encoding.hex_encode(hash.hmac_sha256(key, msg)))
    print(encoding.hex_encode(hash.hmac_sha512(key, msg)))
    print(encoding.hex_encode(hash.hmac_sha1(key, msg)))
    print(encoding.hex_encode(hash.hmac_sha384(lk, msg)))
    print(encoding.hex_encode(hash.hkdf_sha256(key, h("0a0b"), msg, 80)))
    print(encoding.hex_encode(hash.hkdf_sha256(key, h(""), h(""), 42)))
    print(encoding.hex_encode(hash.pbkdf2_sha256("password".as_bytes(), "salt".as_bytes(), 1000, 40)))
    print(encoding.hex_encode(hash.pbkdf2_sha512("password".as_bytes(), "salt".as_bytes(), 50, 70)))
"""
    r = run_gg_source(tmp_path, src)
    assert r.returncode == 0, r.stderr
    want = [hmac.new(key, msg, "sha256").hexdigest(), hmac.new(key, msg, "sha512").hexdigest(),
            hmac.new(key, msg, "sha1").hexdigest(), hmac.new(longkey, msg, "sha384").hexdigest(),
            HKDF(hashes.SHA256(), 80, bytes.fromhex("0a0b"), msg).derive(key).hex(),
            HKDF(hashes.SHA256(), 42, None, b"").derive(key).hex(),
            hashlib.pbkdf2_hmac("sha256", b"password", b"salt", 1000, 40).hex(),
            hashlib.pbkdf2_hmac("sha512", b"password", b"salt", 50, 70).hex()]
    assert r.stdout.splitlines() == want
