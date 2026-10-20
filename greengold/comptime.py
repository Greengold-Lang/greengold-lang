"""Compile-time evaluator: executes `comptime fn` and constant expressions in Python.

Result is returned as a Python value (int/float/bool/str/list/dict, `EnumVal` for an enum); `codegen_llvm`
embeds it as `ir.Constant`. Enums and `match` (literal, range, variant, and guarded arms) are evaluated; heap
values, `defer`, and I/O are reported with `ComptimeError`.
"""
from __future__ import annotations

import copy
import struct as _struct
from typing import Any

from .ast_nodes import (
    ArrayLit, ArrayRepeatLit, Assign, Binary, BlockExpr, BoolLit, Break, Call, Cast, CharLit, ConstDecl, Continue,
    CopyExpr, BorrowExpr, Expr, ExprStmt, FieldAccess, FloatLit, For, ForIn, FormatStr, FuncDecl, If, IndexAccess, IntLit, Name, Pass,
    Program, Return, SoaExpr, Stmt, StrLit, StructLit, Unary, VarDecl, While, Yield, Match, MethodCall, RangePat,
)
from .typeinfo import array_info, is_array_type, is_fn_type

BITS = {"i8": 8, "i16": 16, "i32": 32, "i64": 64, "i128": 128, "isize": 64, "u8": 8, "u16": 16, "u32": 32, "u64": 64,
        "u128": 128, "usize": 64}
SIGNED = {"i8", "i16", "i32", "i64", "i128", "isize"}
FLOATS = {"f16", "f32", "f64"}
STEP_LIMIT = 20_000_000
# `str` methods usable at compile time: name -> (argument count, implementation)
_STR_METHODS = {
    "len": (0, lambda s: len(s.encode("utf-8"))),
    "is_empty": (0, lambda s: s == ""),
    "starts_with": (1, lambda s, p: s.startswith(p)),
    "ends_with": (1, lambda s, p: s.endswith(p)),
    "contains": (1, lambda s, p: p in s),
}


class ComptimeError(Exception):
    pass


class FnRef:
    """A function used as a constant (its address is known at link time)."""

    def __init__(self, key: str) -> None:
        self.key = key

    def __eq__(self, other: object) -> bool:
        return isinstance(other, FnRef) and other.key == self.key

    def __hash__(self) -> int:
        return hash(self.key)


class EnumVal:
    """An enum value at compile time: its type, variant, and payload values."""

    def __init__(self, ty: str, variant: str, payload: list) -> None:
        self.ty, self.variant, self.payload = ty, variant, payload

    def __eq__(self, other: object) -> bool:
        return isinstance(other, EnumVal) and (self.ty, self.variant, self.payload) == (other.ty, other.variant, other.payload)

    def __repr__(self) -> str:
        return f"{self.variant}({', '.join(map(repr, self.payload))})" if self.payload else self.variant


class _Return(Exception):
    def __init__(self, value: Any) -> None:
        self.value = value


class _Break(Exception):
    pass


class _Continue(Exception):
    pass


class _Yield(Exception):
    def __init__(self, value: Any) -> None:
        self.value = value


def wrap_int(v: int, ty: str) -> int:
    bits = BITS[ty]
    v &= (1 << bits) - 1
    if ty in SIGNED and v >= 1 << (bits - 1):
        v -= 1 << bits
    return v


def round_f16(v: float) -> float:
    try:
        return _struct.unpack("e", _struct.pack("e", v))[0]
    except OverflowError:
        return float("inf") if v > 0 else float("-inf")


def round_f32(v: float) -> float:
    try:
        return _struct.unpack("f", _struct.pack("f", v))[0]
    except OverflowError:
        return float("inf") if v > 0 else float("-inf")


def _cdiv(a: int, b: int) -> int:
    q = abs(a) // abs(b)
    return q if (a < 0) == (b < 0) else -q


class Interp:
    def __init__(self, program: Program) -> None:
        self.program = program
        self.funcs: dict[str, FuncDecl] = {
            d.name: d for d in program.decls
            if isinstance(d, FuncDecl) and d.owner is None and not d.type_params and not d.owner_params}
        self.const_decls: dict[str, ConstDecl] = {d.name: d for d in program.decls if isinstance(d, ConstDecl)}
        self.memo: dict[str, Any] = {}
        self.steps = 0
        self.reports: list[tuple[str, str]] | None = None  # ("error" | "note", text) from `compile_error` and `print`; None outside an attribute body

    # -- public interface -------------------------------------------------
    def const_value(self, name: str) -> Any:
        if name in self.memo:
            return self.memo[name]
        d = self.const_decls[name]
        self.memo[name] = None
        v = self.eval(d.value, {})
        self.memo[name] = v
        return v

    def run_attribute(self, handler: FuncDecl, args: list[Any]) -> list[tuple[str, str]]:
        """Runs an attribute's body for one use and returns what it reported: `("error", text)` for each
        `compile_error` and `("note", text)` for each `print`."""
        self.reports = []
        try:
            self.call(handler, args)
            return self.reports
        finally:
            self.reports = None

    def eval_decl(self, d: ConstDecl) -> Any:
        return self.const_value(d.name)

    # -- expressions -----------------------------------------------------
    def tick(self) -> None:
        self.steps += 1
        if self.steps > STEP_LIMIT:
            raise ComptimeError("comptime evaluation took too long (step limit exceeded)")

    def arith(self, op: str, ty: str, a: Any, b: Any) -> Any:
        if ty in FLOATS:
            if op == "+": r = a + b
            elif op == "-": r = a - b
            elif op == "*": r = a * b
            elif op == "/":
                r = a / b if b != 0 else (float("inf") if a > 0 else float("-inf") if a < 0 else float("nan"))
            elif op == "%":
                r = float("nan") if b == 0 else a - b * int(a / b)
            else:
                raise ComptimeError(f"'{op}' is not supported for float")
            return round_f16(r) if ty == "f16" else round_f32(r) if ty == "f32" else r
        if ty == "bool":
            return {"&": a and b, "|": a or b, "^": a != b}[op]
        if op == "+": r = a + b
        elif op == "-": r = a - b
        elif op == "*": r = a * b
        elif op in ("/", "%"):
            if b == 0:
                raise ComptimeError("comptime: division by zero")
            r = _cdiv(a, b) if op == "/" else a - _cdiv(a, b) * b
        elif op == "&": r = a & b
        elif op == "|": r = a | b
        elif op == "^": r = a ^ b
        elif op == "<<":
            if b < 0 or b >= BITS[ty]:
                raise ComptimeError("comptime: shift amount out of bounds")
            r = a << b
        elif op == ">>":
            if b < 0 or b >= BITS[ty]:
                raise ComptimeError("comptime: shift amount out of bounds")
            r = a >> b
        else:
            raise ComptimeError(f"unsupported operator '{op}'")
        return wrap_int(r, ty)

    def eval(self, e: Expr, env: dict[str, Any]) -> Any:
        self.tick()
        ety = getattr(e, "ctor_enum", None)
        if ety is not None:  # `Shape.Circle(1.5)`, `Color.Red`, `Valid(3)`, `None`
            if isinstance(e, Call):
                return EnumVal(ety, e.callee, [copy.deepcopy(self.eval(a, env)) for a in e.args])
            if isinstance(e, MethodCall):
                return EnumVal(ety, e.method, [copy.deepcopy(self.eval(a, env)) for a in e.args])
            if isinstance(e, FieldAccess):
                return EnumVal(ety, e.field_name, [])
            if isinstance(e, Name):
                return EnumVal(ety, e.name, [])
        if isinstance(e, IntLit):
            return float(e.value) if e.ty in FLOATS else e.value
        if isinstance(e, FloatLit):
            return round_f16(float(e.text)) if e.ty == "f16" else round_f32(float(e.text)) if e.ty == "f32" else float(e.text)
        if isinstance(e, BoolLit):
            return e.value
        if isinstance(e, CharLit):
            return e.value
        if isinstance(e, StrLit):
            return e.value
        if isinstance(e, Name):
            if getattr(e, "func_ref", False) and e.name not in env:
                return FnRef(getattr(e, "func_key", e.name))
            if e.name in env:
                return env[e.name]
            if e.name in self.const_decls:
                return self.const_value(e.name)
            raise ComptimeError(f"comptime: '{e.name}' is unknown at compile time")
        if isinstance(e, CopyExpr):
            return copy.deepcopy(self.eval(e.expr, env))
        if isinstance(e, BorrowExpr):
            return self.eval(e.expr, env)
        if isinstance(e, SoaExpr):
            raise ComptimeError("comptime: soa is not supported")
        if isinstance(e, Unary):
            v = self.eval(e.operand, env)
            if e.op == "not":
                return not v
            if e.op == "~":
                return wrap_int(~v, e.ty or "i32")
            return -v if e.ty in FLOATS else wrap_int(-v, e.ty or "i32")
        if isinstance(e, Binary):
            return self._binary(e, env)
        if isinstance(e, FormatStr):
            parts = [self.eval(p, env) for p in e.parts]
            return "".join(str(p).lower() if isinstance(p, bool) else str(p) for p in parts)
        if isinstance(e, Cast):
            return self._cast(self.eval(e.expr, env), e.expr.ty or "i32", e.target_type)
        if isinstance(e, ArrayLit):
            return [copy.deepcopy(self.eval(x, env)) for x in e.elements]
        if isinstance(e, ArrayRepeatLit):
            v = self.eval(e.value, env)
            n = self.eval(e.count, env)
            return [copy.deepcopy(v) for _ in range(n)]
        if isinstance(e, IndexAccess):
            obj, idx = self.eval(e.obj, env), self.eval(e.index, env)
            if isinstance(obj, str):
                obj = list(obj.encode("utf-8"))
            if not 0 <= idx < len(obj):
                raise ComptimeError(f"comptime: index out of bounds ({idx}, length {len(obj)})")
            return obj[idx]
        if isinstance(e, FieldAccess):
            obj = self.eval(e.obj, env)
            if e.field_name == "len":
                return len(obj.encode("utf-8")) if isinstance(obj, str) else len(obj)
            if isinstance(obj, dict) and e.field_name in obj:
                return obj[e.field_name]
            raise ComptimeError(f"comptime: field '{e.field_name}' cannot be read")
        if isinstance(e, StructLit):
            info = self.program.struct_infos.get(e.ty or e.type_name)
            if info is None:
                raise ComptimeError("comptime: unknown struct")
            vals = {f.name: copy.deepcopy(self.eval(f.value, env)) for f in e.fields}
            return {k: vals.get(k, self.zero(t)) for k, t in info.fields.items()}
        if isinstance(e, BlockExpr):
            try:
                self.exec_stmt(e.stmt, env)
            except _Yield as y:
                return y.value
            raise ComptimeError("comptime: expression did not produce a value")
        if isinstance(e, MethodCall):
            recv = self.eval(e.obj, env)
            if isinstance(recv, str) and e.method in _STR_METHODS:
                args = [self.eval(a, env) for a in e.args]
                if len(args) != _STR_METHODS[e.method][0] or not all(isinstance(a, str) for a in args):
                    raise ComptimeError(f"comptime: wrong arguments for str.{e.method}")
                return _STR_METHODS[e.method][1](recv, *args)
            raise ComptimeError(f"comptime: the method '{e.method}' cannot be called at compile time")
        if isinstance(e, Call):
            if e.callee == "compile_error" and self.reports is not None:
                self.reports.append(("error", str(self.eval(e.args[0], env))))
                return None
            if e.callee == "print" and self.reports is not None:
                parts = [self.eval(a, env) for a in e.args]
                self.reports.append(("note", " ".join(str(p).lower() if isinstance(p, bool) else str(p) for p in parts)))
                return None
            if e.ctor_enum is not None or e.callee in ("print", "input", "panic"):
                raise ComptimeError(f"comptime: '{e.callee}' cannot be used at compile time")
            f = self.funcs.get(e.callee)
            if f is None:
                raise ComptimeError(f"comptime: '{e.callee}' cannot be called")
            return self.call(f, [copy.deepcopy(self.eval(a, env)) for a in e.args])
        raise ComptimeError(f"comptime: unsupported expression ({type(e).__name__})")

    def zero(self, ty: str) -> Any:
        if ty in FLOATS:
            return 0.0
        if ty == "bool":
            return False
        if ty in BITS:
            return 0
        if ty == "str":
            return ""
        if is_fn_type(ty):
            return None                 # a function address is filled in by the initializer
        if is_array_type(ty):
            n, el = array_info(ty)
            return [self.zero(el) for _ in range(n)]
        info = self.program.struct_infos.get(ty)
        if info is not None:
            return {k: self.zero(t) for k, t in info.fields.items()}
        raise ComptimeError(f"comptime: no zero value for '{ty}'")

    def _cast(self, v: Any, src: str, dst: str) -> Any:
        if dst in FLOATS:
            r = float(v)
            return round_f16(r) if dst == "f16" else round_f32(r) if dst == "f32" else r
        if dst == "bool":
            return bool(v)
        if dst in BITS:
            if isinstance(v, float):
                if v != v or v in (float("inf"), float("-inf")):
                    return 0
                v = int(v)
            return wrap_int(int(v), dst)
        raise ComptimeError(f"comptime: conversion to '{dst}' is not supported")

    def _binary(self, e: Binary, env: dict[str, Any]) -> Any:
        if e.op == "and":
            return bool(self.eval(e.left, env)) and bool(self.eval(e.right, env))
        if e.op == "or":
            return bool(self.eval(e.left, env)) or bool(self.eval(e.right, env))
        a, b = self.eval(e.left, env), self.eval(e.right, env)
        if e.op == "+" and (isinstance(a, str) or isinstance(b, str)):
            def _to_s(x: Any) -> str:
                return str(x).lower() if isinstance(x, bool) else str(x)
            return _to_s(a) + _to_s(b)
        if e.op in ("==", "!=", "<", "<=", ">", ">="):
            return {"==": a == b, "!=": a != b, "<": a < b, "<=": a <= b, ">": a > b, ">=": a >= b}[e.op]
        return self.arith(e.op, e.ty or e.left.ty or "i32", a, b)

    def _match(self, s: Match, env: dict[str, Any]) -> None:
        v = self.eval(s.scrutinee, env)
        for arm in s.arms:
            names: dict[str, Any] = {}
            if isinstance(v, EnumVal):
                if arm.variant is not None and arm.variant != v.variant:
                    continue
                if arm.variant is not None:
                    names = {b.name: x for b, x in zip(arm.bindings, v.payload) if b.name != "_"}
            elif arm.pats and not any(self._pat_fits(p, v, env) for p in arm.pats):
                continue
            if arm.whole:
                names[arm.whole] = v
            inner = dict(env)
            inner.update(copy.deepcopy(names))
            if arm.guard is not None and not self.eval(arm.guard, inner):
                continue
            try:
                self.exec_block(arm.body, inner)
            finally:
                for k in env:  # changes to outer variables stay; the arm's own names go away
                    if k not in names:
                        env[k] = inner[k]
            return
        raise ComptimeError("comptime: no `match` arm fits the value")

    def _pat_fits(self, p: Any, v: Any, env: dict[str, Any]) -> bool:
        if isinstance(p, RangePat):
            lo, hi = self.eval(p.lo, env), self.eval(p.hi, env)
            return lo <= v <= hi if p.inclusive else lo <= v < hi
        return self.eval(p, env) == v

    # -- functions / statements -------------------------------------------
    def call(self, f: FuncDecl, args: list[Any]) -> Any:
        env = {p.name: a for p, a in zip(f.params, args)}
        try:
            self.exec_block(f.body, env)
        except _Return as r:
            return r.value
        return None

    def exec_block(self, stmts: list[Stmt], env: dict[str, Any]) -> None:
        for s in stmts:
            self.exec_stmt(s, env)

    def _store(self, target: Expr, value: Any, env: dict[str, Any]) -> None:
        if isinstance(target, Name):
            env[target.name] = value
        elif isinstance(target, IndexAccess):
            obj, idx = self.eval(target.obj, env), self.eval(target.index, env)
            if not 0 <= idx < len(obj):
                raise ComptimeError("comptime: index out of bounds")
            obj[idx] = value
        elif isinstance(target, FieldAccess):
            self.eval(target.obj, env)[target.field_name] = value
        else:
            raise ComptimeError("comptime: invalid assignment target")

    def exec_stmt(self, s: Stmt, env: dict[str, Any]) -> None:
        self.tick()
        if isinstance(s, VarDecl):
            env[s.name] = copy.deepcopy(self.eval(s.value, env))
        elif isinstance(s, Assign):
            v = copy.deepcopy(self.eval(s.value, env))
            if s.op != "=":
                cur = self.eval(s.target, env)
                v = self.arith(s.op[:-1], s.target.ty or "i32", cur, v)
            self._store(s.target, v, env)
        elif isinstance(s, ExprStmt):
            self.eval(s.expr, env)
        elif isinstance(s, Return):
            raise _Return(None if s.value is None else copy.deepcopy(self.eval(s.value, env)))
        elif isinstance(s, Yield):
            raise _Yield(self.eval(s.value, env))
        elif isinstance(s, Pass):
            pass
        elif isinstance(s, If):
            for br in s.branches:
                if self.eval(br.cond, env):
                    self.exec_block(br.body, env)
                    return
            if s.else_body is not None:
                self.exec_block(s.else_body, env)
        elif isinstance(s, While):
            while self.eval(s.cond, env):
                try:
                    self.exec_block(s.body, env)
                except _Break:
                    break
                except _Continue:
                    continue
        elif isinstance(s, For):
            lo, hi = self.eval(s.start, env), self.eval(s.end, env)
            st = s.step_value
            stop = hi + ((1 if st > 0 else -1) if s.inclusive else 0)
            for i in range(lo, stop, st):
                env[s.var] = i
                try:
                    self.exec_block(s.body, env)
                except _Break:
                    break
                except _Continue:
                    continue
        elif isinstance(s, ForIn):
            it = self.eval(s.iterable, env)
            if s.count:
                items = list(range(it))
            else:
                items = list(it.encode("utf-8")) if isinstance(it, str) else list(it)
            for n, x in enumerate(items):
                if s.mutable or s.by_ref:
                    raise ComptimeError("comptime: reference loops (a loop that changes its elements, struct elements) are not supported")
                if s.index_var:
                    env[s.index_var] = n
                env[s.var] = copy.deepcopy(x)
                try:
                    self.exec_block(s.body, env)
                except _Break:
                    break
                except _Continue:
                    continue
        elif isinstance(s, Match):
            self._match(s, env)
        elif isinstance(s, Break):
            raise _Break()
        elif isinstance(s, Continue):
            raise _Continue()
        else:
            raise ComptimeError(f"comptime: unsupported statement ({type(s).__name__})")
