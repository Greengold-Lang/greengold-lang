"""std.crypto against the `cryptography` package, plus the published test vectors."""
import os
import random

import pytest

from tests.helpers import run_gg_source

cryptography = pytest.importorskip("cryptography")
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM, ChaCha20Poly1305
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes


def _prog(body: str) -> str:
    return ("import std.crypto\nimport std.encoding\n\nfn h(text: str) -> List[u8]:\n"
            "    return encoding.hex_decode(text).value_or_panic()\n\nfn main():\n" + body)


def test_chacha20poly1305_matches(tmp_path):
    rng = random.Random(1)
    body, want = "", []
    for n_msg, n_aad in [(0, 0), (1, 0), (15, 3), (16, 16), (17, 1), (64, 20), (65, 0), (200, 33), (1000, 7)]:
        key, nonce = rng.randbytes(32), rng.randbytes(12)
        msg, aad = rng.randbytes(n_msg), rng.randbytes(n_aad)
        sealed = ChaCha20Poly1305(key).encrypt(nonce, msg, aad)
        want.append(sealed.hex())
        body += (f'    s = crypto.chacha20poly1305_seal(h("{key.hex()}"), h("{nonce.hex()}"), h("{aad.hex()}"), h("{msg.hex()}"))\n'
                 f'    print(encoding.hex_encode(s))\n')
        # opening gives the message back; a flipped bit gives None
        body += (f'    o = crypto.chacha20poly1305_open(h("{key.hex()}"), h("{nonce.hex()}"), h("{aad.hex()}"), s)\n'
                 f'    print(encoding.hex_encode(o.value_or_panic()))\n')
        want.append(msg.hex())
        body += (f'    s[0] = s[0] ^ 1\n    print(crypto.chacha20poly1305_open(h("{key.hex()}"), h("{nonce.hex()}"), h("{aad.hex()}"), s).is_none())\n')
        want.append("true" if n_msg + 16 > 0 else "true")
    r = run_gg_source(tmp_path, _prog(body))
    assert r.returncode == 0, r.stderr
    assert r.stdout.splitlines() == want


def test_rfc8439_vector(tmp_path):
    key = bytes(range(0x80, 0xA0))
    nonce = bytes.fromhex("070000004041424344454647")
    aad = bytes.fromhex("50515253c0c1c2c3c4c5c6c7")
    msg = b"Ladies and Gentlemen of the class of '99: If I could offer you only one tip for the future, sunscreen would be it."
    r = run_gg_source(tmp_path, _prog(
        f'    print(encoding.hex_encode(crypto.chacha20poly1305_seal(h("{key.hex()}"), h("{nonce.hex()}"), h("{aad.hex()}"), h("{msg.hex()}"))))\n'))
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip().endswith("1ae10b594f09e26a7e902ecbd0600691")  # the tag in RFC 8439 section 2.8.2


@pytest.mark.parametrize("key_len", [16, 24, 32])
def test_aes_gcm_matches(tmp_path, key_len):
    rng = random.Random(key_len)
    body, want = "", []
    for n_msg, n_aad in [(0, 0), (0, 5), (1, 0), (16, 0), (17, 13), (33, 16), (100, 1)]:
        key, nonce = rng.randbytes(key_len), rng.randbytes(12)
        msg, aad = rng.randbytes(n_msg), rng.randbytes(n_aad)
        want.append(AESGCM(key).encrypt(nonce, msg, aad).hex())
        body += (f'    s = crypto.aes_gcm_seal(h("{key.hex()}"), h("{nonce.hex()}"), h("{aad.hex()}"), h("{msg.hex()}"))\n'
                 f'    print(encoding.hex_encode(s))\n')
        want.append(msg.hex())
        body += (f'    print(encoding.hex_encode(crypto.aes_gcm_open(h("{key.hex()}"), h("{nonce.hex()}"), h("{aad.hex()}"), s).value_or_panic()))\n')
        body += f'    s[s.len - 1] = s[s.len - 1] ^ 128\n    print(crypto.aes_gcm_open(h("{key.hex()}"), h("{nonce.hex()}"), h("{aad.hex()}"), s).is_none())\n'
        want.append("true")
    r = run_gg_source(tmp_path, _prog(body))
    assert r.returncode == 0, r.stderr
    assert r.stdout.splitlines() == want


def test_aes_block_known_answer(tmp_path):
    # FIPS-197 appendix C
    r = run_gg_source(tmp_path, _prog(
        '    pt = h("00112233445566778899aabbccddeeff")\n'
        '    print(encoding.hex_encode(crypto.aes_encrypt_block(h("000102030405060708090a0b0c0d0e0f"), pt)))\n'
        '    print(encoding.hex_encode(crypto.aes_encrypt_block(h("000102030405060708090a0b0c0d0e0f1011121314151617"), pt)))\n'
        '    print(encoding.hex_encode(crypto.aes_encrypt_block(h("000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f"), pt)))\n'))
    assert r.returncode == 0, r.stderr
    assert r.stdout.splitlines() == ["69c4e0d86a7b0430d8cdb78070b4c55a", "dda97ca4864cdfe06eaf70a0ec0d7191",
                                     "8ea2b7ca516745bfeafc49904b496089"]


def test_x25519_matches(tmp_path):
    rng = random.Random(25519)
    body, want = "", []
    for _ in range(6):
        a, b = X25519PrivateKey.from_private_bytes(rng.randbytes(32)), X25519PrivateKey.from_private_bytes(rng.randbytes(32))
        from cryptography.hazmat.primitives import serialization as ser
        raw_a = a.private_bytes(ser.Encoding.Raw, ser.PrivateFormat.Raw, ser.NoEncryption())
        pub_b = b.public_key().public_bytes(ser.Encoding.Raw, ser.PublicFormat.Raw)
        pub_a = a.public_key().public_bytes(ser.Encoding.Raw, ser.PublicFormat.Raw)
        want += [pub_a.hex(), a.exchange(b.public_key()).hex()]
        body += (f'    print(encoding.hex_encode(crypto.x25519_base(h("{raw_a.hex()}"))))\n'
                 f'    print(encoding.hex_encode(crypto.x25519(h("{raw_a.hex()}"), h("{pub_b.hex()}"))))\n')
    r = run_gg_source(tmp_path, _prog(body))
    assert r.returncode == 0, r.stderr
    assert r.stdout.splitlines() == want


def test_rfc7748_vector(tmp_path):
    scalar = "a546e36bf0527c9d3b16154b82465edd62144c0ac1fc5a18506a2244ba449ac4"
    u = "e6db6867583030db3594c1a424b15f7c726624ec26b3353b10a903a6d0ab1c4c"
    r = run_gg_source(tmp_path, _prog(f'    print(encoding.hex_encode(crypto.x25519(h("{scalar}"), h("{u}"))))\n'))
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "c3da55379de9c6908e94ea4df28d084f32eccf03491c71f754b4075577a28552"


def test_constant_time_eq_and_zeroize(tmp_path):
    r = run_gg_source(tmp_path, """import std.crypto

fn main():
    a = "secret".as_bytes()
    print(crypto.constant_time_eq(a, "secret".as_bytes()), crypto.constant_time_eq(a, "secreT".as_bytes()), crypto.constant_time_eq(a, "sec".as_bytes()))
    k = List[u8]()
    for i in 0..8:
        k.push(u8(i + 1))
    crypto.zeroize(k)
    total = 0
    for b in k:
        total += i32(b)
    print(total, crypto.random_bytes(16).len)
""")
    assert r.returncode == 0, r.stderr
    assert r.stdout.splitlines() == ["true false false", "0 16"]


def test_ed25519_matches(tmp_path):
    from cryptography.hazmat.primitives import serialization as ser
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    rng = random.Random(8032)
    body, want = "", []
    for n in (0, 1, 31, 64, 200):
        seed, msg = rng.randbytes(32), rng.randbytes(n)
        k = Ed25519PrivateKey.from_private_bytes(seed)
        pub = k.public_key().public_bytes(ser.Encoding.Raw, ser.PublicFormat.Raw)
        sig = k.sign(msg)
        want += [pub.hex(), sig.hex(), "true", "false", "false"]
        body += (f'    pk = crypto.ed25519_public_key(h("{seed.hex()}"))\n    print(encoding.hex_encode(pk))\n'
                 f'    sig = crypto.ed25519_sign(h("{seed.hex()}"), h("{msg.hex()}"))\n    print(encoding.hex_encode(sig))\n'
                 f'    print(crypto.ed25519_verify(pk, h("{msg.hex()}"), sig))\n'
                 f'    sig[10] = sig[10] ^ 1\n    print(crypto.ed25519_verify(pk, h("{msg.hex()}"), sig))\n'
                 f'    sig[10] = sig[10] ^ 1\n    print(crypto.ed25519_verify(pk, h("{msg.hex()}00"), sig))\n')
    r = run_gg_source(tmp_path, _prog(body))
    assert r.returncode == 0, r.stderr
    assert r.stdout.splitlines() == want


def test_ed25519_rfc8032_vector(tmp_path):
    seed = "9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60"
    r = run_gg_source(tmp_path, _prog(
        f'    print(encoding.hex_encode(crypto.ed25519_public_key(h("{seed}"))))\n'
        f'    print(encoding.hex_encode(crypto.ed25519_sign(h("{seed}"), h(""))))\n'))
    assert r.returncode == 0, r.stderr
    assert r.stdout.splitlines()[0] == "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a"
    assert r.stdout.splitlines()[1].startswith("e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e06522490155")
