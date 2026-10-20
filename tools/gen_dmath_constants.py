"""Prints the polynomial coefficients std.dmath needs (Taylor series, correctly rounded from exact fractions)."""
from fractions import Fraction
from math import factorial


def lit(f):
    r = repr(float(f))
    return r


def table(name, values):
    body = ", ".join(lit(v) for v in values)
    return f"const {name}: [{len(values)}]f64 = [{body}]"


# sin x = x * (1 + x^2 * S[0] + x^4 * S[1] + ...), S[k] = (-1)^(k+1) / (2k+3)!
sin_c = [Fraction((-1) ** (k + 1), factorial(2 * k + 3)) for k in range(13)]
# cos x = 1 - x^2/2 + x^4 * C[0] + ...; C[k] = (-1)^(k+2) / (2k+4)!
cos_c = [Fraction((-1) ** (k), factorial(2 * k + 4)) for k in range(12)]
# exp r = 1 + r + r^2/2! + ...; E[k] = 1/k!
exp_c = [Fraction(1, factorial(k)) for k in range(0, 17)]
# atan t = t * (1 - t^2/3 + t^4/5 - ...); A[k] = (-1)^k / (2k+1)
atan_c = [Fraction((-1) ** k, 2 * k + 1) for k in range(14)]
# ln(1+f) = 2s (1 + z/3 + z^2/5 + ...), L[k] = 1/(2k+1)
ln_c = [Fraction(1, 2 * k + 1) for k in range(14)]
print(table("SIN_C", sin_c))
print(table("COS_C", cos_c))
print(table("EXP_C", exp_c))
print(table("ATAN_C", atan_c))
print(table("LN_C", ln_c))
