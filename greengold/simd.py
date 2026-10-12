"""SIMD vector types: `f32x4`, `i32x8`, ... (fixed-width vectors of numbers that the CPU adds in one step).

    v = f32x4(1.0, 2.0, 3.0, 4.0)      # one value per lane
    w = f32x4.splat(0.5)                # the same value in every lane
    x = f32x4.load(xs, i)               # lanes i .. i+4 of a slice (bounds-checked)
    (v * w + x).store(out, i)            # `out` is a `lend []f32` parameter
    print((v + w).sum(), v.lane(2))

`+ - * /` work lane by lane (integer vectors: `+ - *` wrap, and `/` is not defined; `& | ^` too).
`min`, `max`, `sqrt` (float), `sum`, `lane(i)`, and `with_lane(i, x)` are methods. A vector is copied.
"""
from __future__ import annotations

from llvmlite import ir

SIMD_TYPES: dict[str, tuple[str, int]] = {
    "f32x4": ("f32", 4), "f32x8": ("f32", 8), "f64x2": ("f64", 2), "f64x4": ("f64", 4),
    "i32x4": ("i32", 4), "i32x8": ("i32", 8), "i64x2": ("i64", 2), "i64x4": ("i64", 4),
    "i16x8": ("i16", 8), "u8x16": ("u8", 16), "u32x4": ("u32", 4),
}


def is_simd(ty: object) -> bool:
    return isinstance(ty, str) and ty in SIMD_TYPES


def lane_type(ty: str) -> str:
    return SIMD_TYPES[ty][0]


def lanes(ty: str) -> int:
    return SIMD_TYPES[ty][1]


def _is_float(ty: str) -> bool:
    return lane_type(ty) in ("f32", "f64")


class SimdCheckMixin:
    """TypeChecker part for vector types."""

    def _simd_binary(self, e, op: str, lt: str, rt: str) -> str:
        from .typecheck import ERR
        if lt != rt:
            self._err(e, f"Both sides of `{op}` must be the same vector type: found `{lt}` and `{rt}`.",
                      f"Make a vector from a number with `{lt if is_simd(lt) else rt}.splat(x)`.")
            return ERR
        allowed = ("+", "-", "*", "/") if _is_float(lt) else ("+", "-", "*", "&", "|", "^")
        if op not in allowed:
            self._err(e, f"`{op}` is not defined on `{lt}`.",
                      f"Vector operators on `{lt}`: {', '.join(allowed)}. Compare lanes with `lane(i)`.")
            return ERR
        return lt

    def _simd_ctor(self, e) -> str:
        """`f32x4(a, b, c, d)`."""
        ty = e.callee
        n, elem = lanes(ty), lane_type(ty)
        if len(e.args) != n:
            self._err(e, f"`{ty}(...)` takes {n} values, one per lane; found {len(e.args)}.",
                      f"Use `{ty}.splat(x)` for the same value in every lane.")
            self._eval_args_quietly(e.args)
            from .typecheck import ERR
            return ERR
        for a in e.args:
            self._expect_type(elem, self._expr(a, elem), a)
        e.simd = "new"
        return ty

    def _simd_static(self, e) -> str:
        """`f32x4.splat(x)`, `f32x4.load(xs, i)`."""
        from .typecheck import ERR, ParamInfo
        ty = e.obj.name
        elem = lane_type(ty)
        if e.method == "splat":
            params = [ParamInfo("x", elem, "val", None)]
        elif e.method == "load":
            params = [ParamInfo("xs", f"[]{elem}", "val", None), ParamInfo("i", "usize", "val", None)]
        else:
            self._err(e, f"`{ty}` has no associated function `{e.method}`.", f"`{ty}.splat(x)` or `{ty}.load(xs, i)`.")
            self._eval_args_quietly(e.args)
            return ERR
        self._check_args(e, f"{ty}.{e.method}", params, e.args, None)
        e.simd = e.method
        e.owner = ty
        return ty

    def _simd_method(self, e, ty: str) -> str:
        from .typecheck import ERR, VOID, ParamInfo
        elem = lane_type(ty)
        table = {
            "lane": ([ParamInfo("i", "usize", "val", None)], elem),
            "with_lane": ([ParamInfo("i", "usize", "val", None), ParamInfo("x", elem, "val", None)], ty),
            "sum": ([], elem),
            "min": ([ParamInfo("other", ty, "val", None)], ty),
            "max": ([ParamInfo("other", ty, "val", None)], ty),
            "store": ([ParamInfo("xs", f"[]{elem}", "lend", None), ParamInfo("i", "usize", "val", None)], VOID),
        }
        if _is_float(ty):
            table["sqrt"] = ([], ty)
        if e.method not in table:
            self._err(e, f"`{ty}` has no method named `{e.method}`.", f"Methods: {', '.join(table)}.")
            self._eval_args_quietly(e.args)
            return ERR
        params, ret = table[e.method]
        self._check_args(e, f"{ty}.{e.method}", params, e.args, None)
        e.simd = e.method
        e.owner = ty
        return ret


# -- code generation --------------------------------------------------------------------------

def llty(cg, ty: str) -> ir.Type:
    return ir.VectorType(cg.llty(lane_type(ty)), lanes(ty))


def arith(cg, op: str, ty: str, l, r):
    b = cg.b
    if _is_float(ty):
        return {"+": b.fadd, "-": b.fsub, "*": b.fmul, "/": b.fdiv}[op](l, r)
    return {"+": b.add, "-": b.sub, "*": b.mul, "&": b.and_, "|": b.or_, "^": b.xor}[op](l, r)


def _splat(cg, ty: str, x):
    b = cg.b
    v = ir.Constant(llty(cg, ty), ir.Undefined)
    for i in range(lanes(ty)):
        v = b.insert_element(v, x, ir.Constant(ir.IntType(32), i))
    return v


def _span_check(cg, e, i, n, ln):
    """Panics unless lanes `i .. i+n` are inside a slice of length `ln`."""
    b = cg.b
    end = b.add(i, ir.Constant(ir.IntType(64), n))
    bad = b.or_(b.icmp_unsigned("<", end, i), b.icmp_unsigned(">", end, ln))
    cg.fail_if(bad, lambda: cg.panic_call(f"SIMD access past the end of the slice ({n} lanes)", e.line, e.col))


def _lane_check(cg, e, i, n):
    b = cg.b
    cg.fail_if(b.icmp_unsigned(">=", i, ir.Constant(ir.IntType(64), n)),
               lambda: cg.panic_call(f"lane index out of range (0..{n})", e.line, e.col))


def call(cg, e):
    """Code for a vector constructor, associated function, or method (`e.simd` says which)."""
    b = cg.b
    kind = e.simd
    ty = e.owner if kind not in ("new",) else e.callee
    lt = llty(cg, ty)
    elem_lt = lt.element
    n = lanes(ty)
    i64 = ir.IntType(64)
    if kind == "new":
        v = ir.Constant(lt, ir.Undefined)
        for k, a in enumerate(e.args):
            v = b.insert_element(v, cg.expr(a), ir.Constant(ir.IntType(32), k))
        return v
    if kind == "splat":
        return _splat(cg, ty, cg.expr(e.args[0]))
    if kind == "load":
        sl = cg.call_arg(e.args[0], f"[]{lane_type(ty)}")
        ptr, ln = b.extract_value(sl, 0), b.extract_value(sl, 1)
        i = cg.to_i64(cg.expr(e.args[1]), e.args[1].ty)
        if not cg.unchecked:
            _span_check(cg, e, i, n, ln)
        load = b.load(b.bitcast(b.gep(ptr, [i], inbounds=True), lt.as_pointer()))
        load.align = max(1, elem_lt.width // 8 if isinstance(elem_lt, ir.IntType) else (4 if elem_lt == ir.FloatType() else 8))
        return load
    v = cg.expr(e.obj)
    if kind == "store":
        sl = cg.call_arg(e.args[0], f"[]{lane_type(ty)}", mode="lend")
        sl = b.load(sl) if isinstance(sl.type, ir.PointerType) else sl
        ptr, ln = b.extract_value(sl, 0), b.extract_value(sl, 1)
        i = cg.to_i64(cg.expr(e.args[1]), e.args[1].ty)
        if not cg.unchecked:
            _span_check(cg, e, i, n, ln)
        st = b.store(v, b.bitcast(b.gep(ptr, [i], inbounds=True), lt.as_pointer()))
        st.align = 1
        return ir.Constant(ir.IntType(32), 0)
    if kind in ("lane", "with_lane"):
        i = cg.to_i64(cg.expr(e.args[0]), e.args[0].ty)
        if not cg.unchecked:
            _lane_check(cg, e, i, n)
        if kind == "lane":
            return b.extract_element(v, i)
        return b.insert_element(v, cg.expr(e.args[1]), i)
    if kind == "sum":
        acc = b.extract_element(v, ir.Constant(ir.IntType(32), 0))
        for k in range(1, n):
            x = b.extract_element(v, ir.Constant(ir.IntType(32), k))
            acc = b.fadd(acc, x) if _is_float(ty) else b.add(acc, x)
        return acc
    if kind in ("min", "max"):
        w = cg.expr(e.args[0])
        if _is_float(ty):
            less = b.fcmp_ordered("<", v, w)
        elif lane_type(ty).startswith("u"):
            less = b.icmp_unsigned("<", v, w)
        else:
            less = b.icmp_signed("<", v, w)
        return b.select(less, v, w) if kind == "min" else b.select(less, w, v)
    if kind == "sqrt":
        name = f"llvm.sqrt.v{n}f{32 if lane_type(ty) == 'f32' else 64}"
        fn = cg.mod.globals.get(name) or ir.Function(cg.mod, ir.FunctionType(lt, [lt]), name)
        return b.call(fn, [v])
    raise AssertionError(kind)


def show(cg, out, v, ty: str) -> None:
    """Prints a vector as its lanes: `[1, 2, 3, 4]`."""
    b = cg.b
    cg.append_text(out, "[")
    for k in range(lanes(ty)):
        if k:
            cg.append_text(out, ", ")
        cg.append_value(out, b.extract_element(v, ir.Constant(ir.IntType(32), k)), lane_type(ty))
    cg.append_text(out, "]")
