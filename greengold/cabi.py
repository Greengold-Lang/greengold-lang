"""Passing structs by value to C functions and getting them back: the C calling conventions.

LLVM does not apply a platform's C rules to a struct parameter; the front end lowers it (clang does
the same). A struct is first flattened into its scalar leaves (offset, size, kind), then:

  * Windows x64: a struct of 1, 2, 4, or 8 bytes travels as one integer of that size; any other size
    goes as a pointer to a copy the caller makes. A result of 1, 2, 4, or 8 bytes comes back in RAX;
    others are written through a hidden first pointer (`sret`).
  * x86-64 System V (Linux, macOS, BSD): over 16 bytes, the struct is copied onto the stack (`byval`)
    and a result is returned through `sret`. Up to 16 bytes, each 8-byte half is SSE when it holds only
    floats (one `double`, one `float`, or `<2 x float>`) and INTEGER otherwise (an integer of the bytes
    it covers); the halves are passed as separate scalars and a result comes back as `{a, b}`.
  * AArch64 (AAPCS64, Apple included): one to four members of a single float type (an HFA) travel as
    `[N x float]`/`[N x double]`; other structs up to 16 bytes as `[1 x i64]`/`[2 x i64]`; larger ones
    as a pointer to a caller copy, and a larger result through `sret`.

Other targets reject a by-value struct at an `extern` with a message.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from llvmlite import ir

I64 = ir.IntType(64)
F32 = ir.FloatType()
F64 = ir.DoubleType()


@dataclass
class Leaf:
    offset: int
    size: int
    kind: str  # "int" | "float" | "double"


@dataclass
class Plan:
    """How one struct parameter or result crosses the C boundary."""
    how: str                      # "direct" | "indirect" | "byval" | "sret"
    parts: list[ir.Type] = field(default_factory=list)  # "direct": the scalars, in order
    align: int = 8

    @property
    def coerced(self) -> ir.Type | None:
        """The one type the struct's memory is read as (several parts read as a literal struct)."""
        if not self.parts:
            return None
        return self.parts[0] if len(self.parts) == 1 else ir.LiteralStructType(self.parts)


def arch_of(triple: str) -> str | None:
    t = triple.lower()
    if t.startswith(("x86_64", "amd64")):
        return "win64" if ("windows" in t or "mingw" in t or "win32" in t) else "sysv"
    if t.startswith(("aarch64", "arm64")):
        return "aarch64"
    return None


def plan_param(leaves: list[Leaf], size: int, align: int, triple: str) -> Plan | None:
    arch = arch_of(triple)
    if arch == "win64":
        if size in (1, 2, 4, 8):
            return Plan("direct", [ir.IntType(size * 8)], align)
        return Plan("indirect", align=align)
    if arch == "sysv":
        if size > 16 or size == 0:
            return Plan("byval", align=max(align, 8))
        return Plan("direct", _sysv_parts(leaves, size), align)
    if arch == "aarch64":
        hfa = _hfa(leaves)
        if hfa is not None:
            return Plan("direct", [hfa], align)
        if size > 16:
            return Plan("indirect", align=align)
        return Plan("direct", [_aarch64_ints(size)], align)
    return None


def plan_result(leaves: list[Leaf], size: int, align: int, triple: str) -> Plan | None:
    arch = arch_of(triple)
    if arch == "win64":
        if size in (1, 2, 4, 8):
            return Plan("direct", [ir.IntType(size * 8)], align)
        return Plan("sret", align=align)
    if arch == "sysv":
        if size > 16 or size == 0:
            return Plan("sret", align=align)
        return Plan("direct", _sysv_parts(leaves, size), align)
    if arch == "aarch64":
        hfa = _hfa(leaves)
        if hfa is not None:
            return Plan("direct", [hfa], align)
        if size > 16:
            return Plan("sret", align=align)
        return Plan("direct", [_aarch64_ints(size)], align)
    return None


def _sysv_parts(leaves: list[Leaf], size: int) -> list[ir.Type]:
    parts: list[ir.Type] = []
    for start in range(0, size, 8):
        end = min(start + 8, size)
        inside = [lf for lf in leaves if lf.offset < end and lf.offset + lf.size > start]
        if inside and all(lf.kind != "int" for lf in inside):
            if any(lf.kind == "double" for lf in inside):
                parts.append(F64)
            elif len(inside) == 2 or end - start > 4 and any(lf.offset >= start + 4 for lf in inside):
                parts.append(ir.VectorType(F32, 2))  # two floats share the half
            else:
                parts.append(F32)
        else:
            parts.append(ir.IntType((end - start) * 8))
    return parts


def _aarch64_ints(size: int) -> ir.Type:
    return I64 if size <= 8 else ir.ArrayType(I64, 2)  # as clang writes it


def _hfa(leaves: list[Leaf]) -> ir.Type | None:
    kinds = {lf.kind for lf in leaves}
    if not leaves or len(leaves) > 4 or len(kinds) != 1 or kinds == {"int"}:
        return None
    return ir.ArrayType(F64 if kinds == {"double"} else F32, len(leaves))
