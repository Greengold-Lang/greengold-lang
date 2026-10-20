"""Prints the constant tables that std.hash needs (SHA-2 round constants and initial values, Keccak rotations).

Run once; the output is pasted into greengold/std/hash.gg. Kept so the numbers can be checked or regenerated:
  python tools/gen_hash_constants.py
"""
from decimal import Decimal, getcontext
import math

getcontext().prec = 80


def primes(n):
    out, k = [], 2
    while len(out) < n:
        if all(k % p for p in out):
            out.append(k)
        k += 1
    return out


def frac_bits(root_value, bits):
    frac = root_value - int(root_value)
    return int(frac * (1 << bits))


def isqrt_frac(p, bits):
    # floor(frac(sqrt(p)) * 2^bits) computed exactly with integers
    return math.isqrt(p << (2 * bits)) - (math.isqrt(p) << bits)


def icbrt(n):
    lo, hi = 0, 1 << ((n.bit_length() + 2) // 3 + 1)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if mid ** 3 <= n:
            lo = mid
        else:
            hi = mid - 1
    return lo


def cbrt_frac(p, bits):
    return icbrt(p << (3 * bits)) - (icbrt(p) << bits)


def table(name, ty, values, width, per_line):
    lines = []
    for i in range(0, len(values), per_line):
        lines.append("    " + ", ".join(f"0x{v:0{width}X}" for v in values[i:i + per_line]))
    return f"const {name}: [{len(values)}]{ty} = [\n" + ",\n".join(lines) + "\n]\n"


if __name__ == "__main__":
    p64 = primes(80)
    print(table("SHA256_K", "u32", [cbrt_frac(p, 32) for p in p64[:64]], 8, 4))
    print(table("SHA256_H0", "u32", [isqrt_frac(p, 32) for p in p64[:8]], 8, 4))
    print(table("SHA512_K", "u64", [cbrt_frac(p, 64) for p in p64], 16, 2))
    print(table("SHA512_H0", "u64", [isqrt_frac(p, 64) for p in p64[:8]], 16, 2))
    print(table("SHA384_H0", "u64", [isqrt_frac(p, 64) for p in p64[8:16]], 16, 2))
    # Keccak round constants via the LFSR from the specification
    def rc_bit(t):
        if t % 255 == 0:
            return 1
        r = 1
        for _ in range(t % 255):
            r <<= 1
            if r & 0x100:
                r ^= 0x171
        return r & 1
    rcs = []
    for ir in range(24):
        v = 0
        for j in range(7):
            if rc_bit(j + 7 * ir):
                v |= 1 << ((1 << j) - 1)
        rcs.append(v)
    print(table("KECCAK_RC", "u64", rcs, 16, 2))
    rot = [0] * 25
    x, y = 1, 0
    for t in range(24):
        rot[x + 5 * y] = ((t + 1) * (t + 2) // 2) % 64
        x, y = y, (2 * x + 3 * y) % 5
    print("const KECCAK_ROT: [25]u32 = [" + ", ".join(str(r) for r in rot) + "]")
