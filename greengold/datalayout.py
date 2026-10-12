"""Type sizes from an LLVM data layout string, without LLVM.

`abi_size(ty, layout)` is LLVM's ABI ("alloc") size of an llvmlite IR type, as `getTypeAllocSize` gives it:
the store size rounded up to the ABI alignment. Only the parts of the layout that decide sizes are read:
pointer, integer, float, vector, and aggregate alignments.
"""
from __future__ import annotations

from functools import lru_cache

import llvmlite.ir as ir

# LLVM's defaults, for what a layout string does not say (DataLayout.cpp).
_INT = {1: 8, 8: 8, 16: 16, 32: 32, 64: 32}
_FLOAT = {16: 16, 32: 32, 64: 64, 128: 128}
_VEC = {64: 64, 128: 128}


class Layout:
    def __init__(self, text: str) -> None:
        self.ints = dict(_INT)
        self.floats = dict(_FLOAT)
        self.vecs = dict(_VEC)
        self.ptr_bits, self.ptr_align = 64, 64
        self.aggregate_align = 0
        for part in text.split("-"):
            if not part:
                continue
            kind, rest = part[0], part[1:]
            if kind == "p":
                space, _, specs = rest.partition(":")
                if space in ("", "0") and specs:
                    nums = [int(x) for x in specs.split(":")]
                    self.ptr_bits = nums[0]
                    self.ptr_align = nums[1] if len(nums) > 1 else nums[0]
            elif kind in "ifv" and rest[:1].isdigit():
                width, _, specs = rest.partition(":")
                abi = int(specs.split(":")[0]) if specs else int(width)
                {"i": self.ints, "f": self.floats, "v": self.vecs}[kind][int(width)] = abi
            elif kind == "a" and rest.startswith(":"):
                self.aggregate_align = int(rest[1:].split(":")[0])

    def int_align(self, bits: int) -> int:
        """Bytes. An unlisted width takes the next wider listed one, or the widest when it is wider than all."""
        if bits in self.ints:
            return max(1, self.ints[bits] // 8)
        wider = [w for w in self.ints if w > bits]
        return max(1, self.ints[min(wider) if wider else max(self.ints)] // 8)

    def align(self, ty: ir.Type) -> int:
        if isinstance(ty, ir.IntType):
            return self.int_align(ty.width)
        if isinstance(ty, (ir.HalfType, ir.FloatType, ir.DoubleType)):
            bits = {ir.HalfType: 16, ir.FloatType: 32, ir.DoubleType: 64}[type(ty)]
            return max(1, self.floats.get(bits, bits) // 8)
        if isinstance(ty, ir.PointerType):
            return max(1, self.ptr_align // 8)
        if isinstance(ty, ir.ArrayType):
            return self.align(ty.element)
        if isinstance(ty, ir.VectorType):
            bits = ty.count * _bits(ty.element, self)
            if bits in self.vecs:
                return max(1, self.vecs[bits] // 8)
            size = (bits + 7) // 8
            return 1 << max(0, (size - 1).bit_length())  # the next power of two
        if isinstance(ty, (ir.LiteralStructType, ir.IdentifiedStructType)):
            if getattr(ty, "packed", False):
                return 1
            elems = ty.elements or ()
            return max([max(1, self.aggregate_align // 8)] + [self.align(e) for e in elems])
        raise TypeError(f"no size for {ty}")

    def size(self, ty: ir.Type) -> int:
        """Alloc size in bytes."""
        if isinstance(ty, ir.ArrayType):
            return ty.count * self.size(ty.element)
        if isinstance(ty, (ir.LiteralStructType, ir.IdentifiedStructType)):
            packed = getattr(ty, "packed", False)
            off = 0
            for e in ty.elements or ():
                if not packed:
                    off = _round(off, self.align(e))
                off += self.size(e)
            return _round(off, self.align(ty))
        return _round((_bits(ty, self) + 7) // 8, self.align(ty))


def _bits(ty: ir.Type, layout: Layout) -> int:
    if isinstance(ty, ir.IntType):
        return ty.width
    if isinstance(ty, ir.HalfType):
        return 16
    if isinstance(ty, ir.FloatType):
        return 32
    if isinstance(ty, ir.DoubleType):
        return 64
    if isinstance(ty, ir.PointerType):
        return layout.ptr_bits
    if isinstance(ty, ir.VectorType):
        return ty.count * _bits(ty.element, layout)
    raise TypeError(f"no size for {ty}")


def _round(n: int, align: int) -> int:
    return (n + align - 1) // align * align


@lru_cache(maxsize=None)
def parse(text: str) -> Layout:
    return Layout(text)


def abi_size(ty: ir.Type, layout: str) -> int:
    return parse(layout).size(ty)
