"""Generates LLVM IR from type-checked AST (llvmlite.ir).

Mappings:
  i8..i64/u8..u64 -> iN, isize/usize -> i64, f32/f64 -> float/double, bool -> i1
  string / slice  -> { T*, i64 }, array -> [N x T], Box -> { T* }, List -> { T*, i64, i64 }
  struct -> identified struct, enum -> { i32 tag, [K x i64] payload }
  `read`/`lend` parameter -> T* ; `consume` and default -> by value
Ownership: `i1` liveness flag (alloca) for each owned variable; `drop` is called at end of scope.
"""
from __future__ import annotations

import sys
from contextlib import contextmanager
from typing import Any, Callable

import llvmlite.ir as ir

from .ast_nodes import (
    Apply,
    ArrayLit, ArrayRepeatLit, Assign, Binary, BlockExpr, BoolLit, Break, Call, Cast, CharLit, ConstDecl, Continue,
    CopyExpr, BorrowExpr, Defer, Expr, ExprStmt, ExternFuncDecl, FieldAccess, FloatLit, For, ForIn, FormatStr, FuncDecl, If, IndexAccess,
    IntLit, Match, MethodCall, Name, Node, Pass, Program, RangePat, Return, SliceExpr, SoaExpr, Stmt, StrLit, StructLit, Try,
    Unary, VarDecl, While, Yield, Require, Wrapping, OverflowMode, unparse,
)
from .comptime import ComptimeError, EnumVal, Interp
from . import cabi, simd
from .counters import mark_bounded_counters
from .typeinfo import (
    TYPE_ALIASES, INT_RANGES,
    EnumInfo, StructInfo, array_info, func_cname, generic_parts, heap_inner, heap_kind, is_array_type, is_slice_type,
    is_ptr_type, needs_drop, ptr_elem, slice_elem_type, fn_parts, is_fn_type,
    is_bounded_int, bounded_int_info, make_bounded_int, int_base, is_boxed_fn, is_dyn_type, dyn_feature,
)

I1, I8, I16, I32, I64 = (ir.IntType(n) for n in (1, 8, 16, 32, 64))


class _VolatileLoad(ir.instructions.LoadInstr):
    """`load volatile`: llvmlite has no flag for it."""

    def descr(self, buf):
        [val] = self.operands
        buf.append(f"load volatile {val.type.pointee}, {val.type} {val.get_reference()}\n")


class _VolatileStore(ir.instructions.StoreInstr):
    def descr(self, buf):
        val, ptr = self.operands
        buf.append(f"store volatile {val.type} {val.get_reference()}, {ptr.type} {ptr.get_reference()}\n")
F32, F64 = ir.FloatType(), ir.DoubleType()
VOID = ir.VoidType()
I8P = I8.as_pointer()

BITS = {"i8": 8, "i16": 16, "i32": 32, "i64": 64, "isize": 64, "u8": 8, "u16": 16, "u32": 32, "u64": 64,
        "usize": 64, "bool": 1}
SIGNED = {"i8", "i16", "i32", "i64", "isize"}
INTS = set(BITS) - {"bool"}
FLOATS = {"f32", "f64"}
COMPARE = {"==", "!=", "<", "<=", ">", ">="}


class CodegenError(Exception):
    pass


class SoaVar:
    """`p = soa Array[Particle, N]`: separate `[N x T]` array for each struct field (SIMD-friendly layout)."""

    def __init__(self, sty: str, n: int, fields: dict[str, ir.Value]) -> None:
        self.sty, self.n, self.fields = sty, n, fields


class SliceVal:
    """Carries `{ptr, len}` as SSA values without reloading from stack on every access."""

    def __init__(self, ptr: ir.Value, len_val: ir.Value, struct_val: ir.Value | None = None) -> None:
        self.ptr = ptr
        self.len = len_val
        self._struct = struct_val

    def get_struct(self, b: ir.IRBuilder, sty: ir.Type) -> ir.Value:
        if self._struct is not None:
            return self._struct
        v = ir.Constant(sty, ir.Undefined)
        v = b.insert_value(v, self.ptr, 0)
        # Not cached: the first use may sit in a branch that does not dominate the later ones.
        return b.insert_value(v, self.len, 1)


def _walk(node: Any):
    if isinstance(node, Node):
        yield node
        for v in node.__dict__.values():
            if isinstance(v, (Node, list)):
                yield from _walk(v)
    elif isinstance(node, list):
        for x in node:
            yield from _walk(x)


def native_triple(target: str | None = None) -> str:
    """Target triple: mingw-w64 ABI on Windows (linked with gcc/clang), host machine otherwise."""
    if target == "bare-metal":
        return "x86_64-unknown-none-elf"
    if target and target != "native":
        from .targets import triple_of
        return triple_of(target)
    triple = _host_triple()
    if "windows" in triple:
        return "x86_64-w64-windows-gnu"
    return triple


def target_os(triple: str) -> str:
    """`windows`, `macos`, `linux`, or `none` (bare metal) for an LLVM target triple."""
    if "windows" in triple or "mingw" in triple:
        return "windows"
    if "darwin" in triple or "apple" in triple or "macos" in triple:
        return "macos"
    if "linux" in triple:
        return "linux"
    return "none"


def is_32bit_triple(triple: str) -> bool:
    """Whether `size_t` is 32 bits for this target. `arm64` and `aarch64` are 64-bit; only 32-bit ARM names
    (`arm`, `armv7...`, `thumbv7em`) are not, so a plain `startswith("arm")` would be wrong."""
    arch = triple.split("-", 1)[0]
    return arch in ("wasm32", "i386", "i486", "i586", "i686", "riscv32", "arm", "armeb") or arch.startswith(("armv", "thumb"))


def target_arch(triple: str) -> str:
    """The CPU family of a triple: `x86_64`, `aarch64`, `riscv64`, `wasm32`, ..."""
    arch = triple.split("-", 1)[0]
    return {"amd64": "x86_64", "arm64": "aarch64"}.get(arch, arch)


def _host_triple() -> str:
    from .llvm_driver import backend
    if backend() == "llvmlite":
        import llvmlite.binding as llvm
        return llvm.get_process_triple()
    import platform
    arch = {"amd64": "x86_64", "x64": "x86_64", "arm64": "aarch64"}.get(platform.machine().lower(),
                                                                       platform.machine().lower())
    if sys.platform == "win32":
        return f"{arch}-w64-windows-gnu"
    if sys.platform == "darwin":
        return f"{'arm64' if arch == 'aarch64' else arch}-apple-darwin"
    return f"{arch}-unknown-linux-gnu"


def _old_llvm() -> bool:
    """LLVM 14 inside llvmlite before 0.45 (the legacy pass manager)."""
    from .llvm_driver import backend
    if backend() != "llvmlite":
        return False
    import llvmlite.binding as llvm
    return not hasattr(llvm, "create_pass_builder")


def init_llvm() -> None:
    from .llvm_driver import backend
    if backend() != "llvmlite":
        return
    import llvmlite.binding as llvm
    try:
        llvm.initialize()
    except Exception:  # not needed in newer llvmlite versions
        pass
    llvm.initialize_all_targets()
    llvm.initialize_all_asmprinters()
    llvm.initialize_native_asmparser()  # inline `asm` is parsed when the object file is written


def _wrap_const(v: int, bits: int) -> int:
    v &= (1 << bits) - 1
    return v - (1 << bits) if bits > 1 and v >= 1 << (bits - 1) else v


class LLVMGen:
    def __init__(self, program: Program, filename: str = "<source>", release: bool = False, unchecked: bool = False,
                 target: str | None = None, leakcheck: bool = False, freestanding: bool = False,
                 debug: bool = False) -> None:
        init_llvm()
        self.program = program
        self.filename = filename
        self.unchecked = unchecked
        self.leakcheck = leakcheck
        self.freestanding = freestanding
        self.triple = native_triple(target)
        self.windows = "windows" in self.triple
        self.wasi = self.triple.startswith("wasm32") and self.triple.endswith("wasi")
        self.wasi_declared: dict[str, tuple[ir.Type, bool]] = {}  # wasm32 C function -> (declared result, signed)
        self.size_t = I32 if is_32bit_triple(self.triple) else I64
        self.mod = ir.Module(name=filename, context=ir.Context())  # fresh context: named types must not leak between compilations
        self.mod.triple = self.triple
        from .debuginfo import DebugInfo
        self.di = DebugInfo(self.mod, filename, release) if debug else None
        self.di_scope = None  # the DISubprogram of the function being generated
        self.target_data = None
        self.layout_text: str | None = None  # the data layout, when an outside LLVM supplies it
        from .llvm_driver import backend
        if backend() == "llvmlite":
            import llvmlite.binding as llvm
            try:
                tm = llvm.Target.from_triple(self.triple).create_target_machine()
                self.target_data = tm.target_data
                self.mod.data_layout = str(tm.target_data)
            except Exception:
                pass
        else:
            from . import llvm_tools
            self.layout_text = llvm_tools.data_layout(self.triple)
            if self.layout_text is None and self.triple.startswith("wasm32"):
                self.layout_text = "e-m:e-p:32:32-i64:64-n32:64-S128"  # no LLVM here (the browser): the fixed layout
            if self.layout_text is not None:
                self.mod.data_layout = self.layout_text
        self._abi_sizes: dict[str, int | None] = {}
        self.type_infos: dict[str, StructInfo | EnumInfo] = {}
        self._lt: dict[str, ir.Type] = {}
        self.strs: dict[str, ir.GlobalVariable] = {}
        self.rt: dict[str, ir.Function] = {}
        self.drops: dict[str, ir.Function] = {}
        self.clones: dict[str, ir.Function] = {}
        self.shows: dict[str, ir.Function] = {}
        self.c_plans: dict[str, tuple] = {}  # C symbol -> (parameter plans, result plan, result type): cabi
        self.eqs: dict[str, ir.Function] = {}  # structural `==` (eq_fn)
        self.hashes: dict[str, ir.Function] = {}  # structural `hash` (hash_fn)
        self.jsons: dict[str, ir.Function] = {}  # `to_json` per type (json_fn)
        self.jdecs: dict[str, ir.Function] = {}  # `from_json` per type (json_dec_fn)
        self.temp_drops: list[tuple[ir.Value, str, Expr]] | None = None  # owned temporaries lent to the current call
        self.cur_stmt: Stmt | None = None
        self.vec_fns: dict[tuple[str, str], ir.Function] = {}
        self.funcs: dict[str, ir.Function] = {}
        self.externs: dict[str, ir.Function] = {}
        self.consts: dict[str, ir.GlobalVariable] = {}
        self.const_init: list[tuple[ConstDecl, ir.GlobalVariable]] = []
        self.interp = Interp(program)
        # function state
        self.b: ir.IRBuilder = None  # type: ignore[assignment]
        self.entry_b: ir.IRBuilder = None  # type: ignore[assignment]
        self.fn: ir.Function = None  # type: ignore[assignment]
        self.vars: dict[str, ir.Value] = {}
        self.flags: dict[str, ir.Value] = {}
        self.scopes: list[list[tuple]] = []
        self.loops: list[tuple[ir.Block, ir.Block, int]] = []
        self.yields: list[ir.Value] = []
        self.cur_ret = "void"
        self.cur_ret_view = False
        self.yield_ptr = False
        self.ref_locals: set[str] = set()
        self.in_main = False
        self.uid = 0
        self.vectorize = False
        self.func_decls: dict[str, FuncDecl] = {}
        self._loop_ids = 0
        self.safe_loops: list[tuple[str, set[str]]] = []
        self.len_equiv: dict[str, set[str]] = {}
        self.cur_func_overflow: str | None = None
        self.wrapping_depth: int = 0
        self._range_meta_i64_pos: ir.MetaData | None = None
        self._range_metas: dict[tuple[ir.Type, int, int], ir.MetaData] = {}
        self._prof_cold_meta: ir.MetaData | None = None

    def is_wrapping(self) -> bool:
        return self.wrapping_depth > 0 or self.cur_func_overflow == "wrap"

    def range_meta_i64_pos(self) -> ir.MetaData:
        if self._range_meta_i64_pos is None:
            self._range_meta_i64_pos = self.mod.add_metadata([
                ir.Constant(I64, 0),
                ir.Constant(I64, (1 << 63) - 1),
            ])
        return self._range_meta_i64_pos

    def range_meta(self, llty: ir.Type, lo: int, hi: int) -> ir.MetaData:
        key = (llty, lo, hi)
        if key not in self._range_metas:
            self._range_metas[key] = self.mod.add_metadata([
                ir.Constant(llty, lo),
                ir.Constant(llty, hi),
            ])
        return self._range_metas[key]

    def prof_cold_meta(self) -> ir.MetaData:
        if self._prof_cold_meta is None:
            self._prof_cold_meta = self.mod.add_metadata([
                ir.MetaDataString(self.mod, "branch_weights"),
                ir.Constant(I32, 1),
                ir.Constant(I32, 1048575),
            ])
        return self._prof_cold_meta

    def get_len_equivalences(self, name: str) -> set[str]:
        equiv = self.len_equiv.get(name)
        if equiv is not None:
            return set(equiv)
        return {name}

    # -- tipler -----------------------------------------------------------
    def nd(self, ty: str | None) -> bool:
        return bool(ty) and needs_drop(ty, self.program.struct_infos, self.program.enum_infos)  # type: ignore[arg-type]

    def llty(self, ty: str | None) -> ir.Type:
        if ty is None or ty == "void":
            return VOID
        got = self._lt.get(ty)
        if got is not None:
            return got
        t = self._build_type(ty)
        self._lt[ty] = t
        return t

    def _build_type(self, ty: str) -> ir.Type:
        ty = TYPE_ALIASES.get(ty, ty)
        if ty in simd.SIMD_TYPES:
            return simd.llty(self, ty)
        if is_dyn_type(ty):  # `dyn F`: { the value on the heap, its table: drop, then one entry per method }
            return ir.LiteralStructType([I8P, I8P.as_pointer()])
        if is_boxed_fn(ty):  # owned closure: { code, environment }
            return ir.LiteralStructType([I8P, I8P])
        if is_fn_type(ty):  # function pointer
            ps, r = fn_parts(ty)
            return ir.FunctionType(self.llty(r), [self.llty(p) for p in ps]).as_pointer()
        if is_ptr_type(ty):  # ham pointer (FFI); `*void` -> i8*
            el = ptr_elem(ty)
            return (I8 if el == "void" else self.llty(el)).as_pointer()
        if is_bounded_int(ty):
            base, _, _ = bounded_int_info(ty)
            return self.llty(base)
        if ty in BITS:
            return ir.IntType(BITS[ty])
        if ty == "f32":
            return F32
        if ty == "f64":
            return F64
        if ty == "str" or is_slice_type(ty):
            elem = I8 if ty == "str" else self.llty(slice_elem_type(ty))
            return ir.LiteralStructType([elem.as_pointer(), I64])
        if is_array_type(ty):
            n, elem = array_info(ty)
            return ir.ArrayType(self.llty(elem), n)
        hk = heap_kind(ty)
        if hk == "Box":
            return ir.LiteralStructType([self.llty(heap_inner(ty)).as_pointer()])
        if hk in ("Shared", "Arc"):  # pointer to { count, value }
            return ir.LiteralStructType([ir.LiteralStructType([I64, self.llty(heap_inner(ty))]).as_pointer()])
        if hk == "List":
            return ir.LiteralStructType([self.llty(heap_inner(ty)).as_pointer(), I64, I64])
        info = self.type_infos.get(ty)
        if info is None:
            raise CodegenError(f"unknown type '{ty}'")
        name = self._ident(ty)
        t = self.mod.context.get_identified_type(name)
        self._lt[ty] = t  # registered early for recursive types
        if isinstance(info, StructInfo) and getattr(info.decl, "is_union", False):
            size, al = self.size_align(ty)  # the most aligned field first, then bytes up to the size
            widest = max(info.fields.values(), key=lambda f: self.size_align(f)[1])
            first = self.llty(widest)
            rest = size - self.size_align(widest)[0]
            t.set_body(*([first] + ([ir.ArrayType(I8, rest)] if rest > 0 else [])))
        elif isinstance(info, StructInfo):
            elems = []
            for fname, fty in info.fields.items():
                ft = self.llty(fty)
                elems.append(ft.as_pointer() if fname in info.field_modes else ft)
            align = getattr(info.decl, "align", 0)
            if align:  # a zero-length member of that alignment raises the struct's alignment and rounds its size
                elems.append(ir.ArrayType(ir.VectorType(I32, align // 4) if align >= 16 else ir.IntType(8 * align), 0))
            if getattr(info.decl, "packed", False):
                t.packed = True
            t.set_body(*elems)
        else:
            words = (self.enum_payload_size(info) + 7) // 8
            t.set_body(I32, ir.ArrayType(I64, words))
        return t

    @staticmethod
    def _ident(ty: str) -> str:
        return "".join(c if c.isalnum() or c == "_" else "_" for c in ty)

    def size_align(self, ty: str) -> tuple[int, int]:
        if is_boxed_fn(ty) or is_dyn_type(ty):
            return 16, 8
        if ty in simd.SIMD_TYPES:
            size = self.size_align(simd.lane_type(ty))[0] * simd.lanes(ty)
            return size, size
        if is_ptr_type(ty) or is_fn_type(ty):
            return 8, 8
        if is_bounded_int(ty):
            base, _, _ = bounded_int_info(ty)
            return self.size_align(base)
        if ty in ("i8", "u8", "bool"):
            return 1, 1
        if ty in ("i16", "u16"):
            return 2, 2
        if ty in ("i32", "u32", "f32"):
            return 4, 4
        if ty in BITS or ty == "f64":
            return 8, 8
        if ty == "str" or is_slice_type(ty):
            return 16, 8
        if is_array_type(ty):
            n, elem = array_info(ty)
            s, a = self.size_align(elem)
            return s * n, a
        hk = heap_kind(ty)
        if hk in ("Box", "Shared", "Arc"):
            return 8, 8
        if hk == "List":
            return 24, 8
        info = self.type_infos[ty]
        if isinstance(info, StructInfo) and getattr(info.decl, "is_union", False):
            sizes = [self.size_align(f) for f in info.fields.values()]
            al = max(a for _, a in sizes)
            return (max(s for s, _ in sizes) + al - 1) // al * al, al
        if isinstance(info, StructInfo) and getattr(info.decl, "packed", False):
            return sum(8 if f in info.field_modes else self.size_align(t)[0]
                       for f, t in info.fields.items()), 1
        if isinstance(info, StructInfo):
            size, al = self._layout([8 if f in info.field_modes else None for f in info.fields],
                                    list(info.fields.values()))
            want = getattr(info.decl, "align", 0)
            if want > al:
                al = want
                size = (size + al - 1) // al * al
            return size, al
        return 8 + 8 * ((self.enum_payload_size(info) + 7) // 8), 8

    def _layout(self, ptr_flags: list, tys: list[str]) -> tuple[int, int]:
        off, al = 0, 1
        for p, t in zip(ptr_flags, tys):
            s, a = (8, 8) if p else self.size_align(t)
            off = (off + a - 1) // a * a + s
            al = max(al, a)
        return (off + al - 1) // al * al, al

    def enum_payload_size(self, info: EnumInfo) -> int:
        best = 0
        for v in info.variants.values():
            if v.payload:
                best = max(best, self._layout([None] * len(v.payload), list(v.payload))[0])
        return best

    def payload_type(self, payload: list[str]) -> ir.Type:
        return ir.LiteralStructType([self.llty(t) for t in payload])

    # -- sabitler / string'ler -------------------------------------------
    def cstr(self, text: str) -> ir.Value:
        """NUL'lu C string -> i8* (sabit ifade)."""
        g = self._str_global(text)
        return g.gep([ir.Constant(I32, 0), ir.Constant(I32, 0)])

    def _str_global(self, text: str) -> ir.GlobalVariable:
        g = self.strs.get(text)
        if g is None:
            data = bytearray(text.encode("utf-8") + b"\0")
            g = ir.GlobalVariable(self.mod, ir.ArrayType(I8, len(data)), f".str.{len(self.strs)}")
            g.initializer = ir.Constant(g.value_type, data)
            g.global_constant = True
            g.linkage = "private"
            g.unnamed_addr = True
            self.strs[text] = g
        return g

    def str_const(self, text: str) -> ir.Constant:
        return ir.Constant(self.llty("str"), [self.cstr(text), ir.Constant(I64, len(text.encode("utf-8")))])

    def to_const(self, v: Any, ty: str) -> ir.Constant:
        """Converts comptime Python value to `ir.Constant`."""
        if is_bounded_int(ty):
            base, _, _ = bounded_int_info(ty)
            return self.to_const(v, base)
        lt = self.llty(ty)
        if ty in FLOATS:
            return ir.Constant(lt, float(v))
        if ty == "bool":
            return ir.Constant(lt, 1 if v else 0)
        if ty in BITS:
            return ir.Constant(lt, _wrap_const(int(v), BITS[ty]))
        if ty == "str":
            return self.str_const(v)
        if is_array_type(ty):
            _, elem = array_info(ty)
            return ir.Constant(lt, [self.to_const(x, elem) for x in v])
        info = self.type_infos.get(ty)
        if isinstance(info, StructInfo) and not info.field_modes:
            return ir.Constant(lt, [self.to_const(v[k], t) for k, t in info.fields.items()])
        if isinstance(info, EnumInfo) and isinstance(v, EnumVal):
            return self.enum_const(v, ty, info)
        raise ComptimeError(f"'{ty}' cannot be embedded as a constant")

    def enum_const(self, v: "EnumVal", ty: str, info: EnumInfo) -> ir.Constant:
        """An enum constant: the tag, and the payload's bytes packed into the payload words."""
        payload = list(info.variants[v.variant].payload)
        words_t = self.llty(ty).elements[1]
        raw = bytearray(words_t.count * 8)
        off = 0
        for val, pty in zip(v.payload, payload):
            size, al = self.size_align(pty)
            off = (off + al - 1) // al * al
            raw[off:off + size] = self._const_bytes(val, pty)
            off += size
        words = [int.from_bytes(raw[i:i + 8], "little") for i in range(0, len(raw), 8)]
        return ir.Constant(self.llty(ty), [ir.Constant(I32, self.tag_index(info, v.variant)),
                                           ir.Constant(words_t, [ir.Constant(I64, w) for w in words])])

    def _const_bytes(self, v: Any, ty: str) -> bytes:
        import struct as _st
        if ty in FLOATS:
            return _st.pack("<f" if ty == "f32" else "<d", float(v))
        if ty == "bool":
            return bytes([1 if v else 0])
        if ty in BITS:
            n = self.size_align(ty)[0]
            return (int(v) & ((1 << (8 * n)) - 1)).to_bytes(n, "little")
        if is_array_type(ty):
            _, elem = array_info(ty)
            return b"".join(self._const_bytes(x, elem) for x in v)
        info = self.type_infos.get(ty)
        if isinstance(info, StructInfo) and not info.field_modes:
            out = bytearray(self.size_align(ty)[0])
            off = 0
            for k, fty in info.fields.items():
                size, al = self.size_align(fty)
                off = (off + al - 1) // al * al
                out[off:off + size] = self._const_bytes(v[k], fty)
                off += size
            return bytes(out)
        raise ComptimeError(f"a `{ty}` payload cannot be part of a constant enum")

    # -- program ----------------------------------------------------------
    def generate(self) -> str:
        self.type_infos = {**self.program.struct_infos, **self.program.enum_infos}
        decls = self.program.decls
        funcs = [d for d in decls if isinstance(d, FuncDecl) and not d.type_params and not d.owner_params]
        funcs += self.program.func_instances
        externs = [d for d in decls if isinstance(d, ExternFuncDecl)]
        for ext in externs:
            self._declare_extern(ext)
        for c in (d for d in decls if isinstance(d, ConstDecl)):
            self._const(c)
        for f in funcs:
            self._declare_func(f)
        for f in funcs:
            self._define_func(f)
        self._emit_main(funcs)
        return str(self.mod)

    def _const(self, d: ConstDecl) -> None:
        assert d.ty is not None
        lt = self.llty(d.ty)
        ckey = getattr(d, "sym_key", None) or d.name
        g = ir.GlobalVariable(self.mod, lt, "gg_const_" + self._ident(ckey))
        g.linkage = "internal"
        try:
            value = getattr(d, "comptime_value", None)
            g.initializer = self.to_const(value if value is not None else self.interp.eval_decl(d), d.ty)
            g.global_constant = not getattr(d, "is_static", False)
        except ComptimeError as err:
            if self._has_comptime_call(d.value):
                raise CodegenError(f"comptime value could not be computed ('{d.name}'): {err}") from None
            g.initializer = ir.Constant(lt, None)
            self.const_init.append((d, g))
        self.consts[ckey] = g

    def _has_comptime_call(self, e: Any) -> bool:
        if isinstance(e, Call) and e.callee in self.interp.funcs and self.interp.funcs[e.callee].is_comptime:
            return True
        if isinstance(e, Node):
            return any(self._has_comptime_call(v) if isinstance(v, Node) else
                       any(self._has_comptime_call(x) for x in v) if isinstance(v, list) else False
                       for v in e.__dict__.values())
        return False

    @staticmethod
    def fname(f: FuncDecl) -> str:
        if f.inst_key is not None:
            return func_cname(f.inst_key)
        # `owner` is already the canonical type (`string` or `combat::Player`).
        if f.owner:
            return func_cname(f"{f.owner}.{f.name}")
        slug = "" if getattr(f, "from_prelude", False) else (getattr(f, "module_slug", "") or "")
        if slug:
            return func_cname(f"{slug}::{f.name}")
        return f.name

    def _param_ty(self, p: Any) -> str:
        return getattr(p, "ty", None) or p.type_ref.name

    @staticmethod
    def _by_ptr(p: Any, ty: str) -> bool:
        return p.mode in ("read", "lend") and not is_slice_type(ty)

    def _declare_func(self, f: FuncDecl) -> None:
        ret = getattr(f, "ret_ty", None) or (f.ret.name if f.ret else "void")
        args = []
        for p in f.params:
            ty = self._param_ty(p)
            lt = self.llty(ty)
            if self._split(p, ty):  # exclusive slice: (T* noalias, i64) pair
                args += [self.llty(slice_elem_type(ty)).as_pointer(), I64]
            else:
                args.append(lt.as_pointer() if self._by_ptr(p, ty) else lt)
        is_main = f.name == "main" and f.owner is None
        ret_ll = VOID if is_main else self.llty(ret)
        if not is_main and getattr(f, "ret_view", False):
            ret_ll = ret_ll.as_pointer()
        fn = ir.Function(self.mod, ir.FunctionType(ret_ll, args), "gg_" + self.fname(f))
        fn.linkage = "internal"
        i = 0
        for p in f.params:
            ty = self._param_ty(p)
            if self._split(p, ty):
                fn.args[i].name, fn.args[i + 1].name = p.name + ".ptr", p.name + ".len"
                fn.args[i].add_attribute("noalias")
                i += 2
                continue
            fn.args[i].name = p.name
            if self._by_ptr(p, ty):
                # `lend` is exclusive and the borrow checker rejects any other access to that memory
                # during the call, so the pointer cannot alias. `read` may alias other `read`s.
                if p.mode == "lend" or getattr(p, "exclusive", False):
                    fn.args[i].add_attribute("noalias")
                fn.args[i].add_attribute("nonnull")
                size = self.abi_size(ty)
                if size:
                    fn.args[i].attributes.dereferenceable = size
            i += 1
        self.funcs[self.fname(f)] = fn
        self.func_decls[self.fname(f)] = f

    @staticmethod
    def _split(p: Any, ty: str) -> bool:
        """`lend` and `exclusive` slices are passed as a (T* noalias, i64) pair."""
        return (p.mode == "lend" or getattr(p, "exclusive", False)) and is_slice_type(ty)

    def abi_size(self, ty: str) -> int | None:
        """Byte size of the Greengold type `ty` on the target, or None when unknown."""
        if ty not in self._abi_sizes:
            size = None
            if self.target_data is not None:
                try:
                    size = self.llty(ty).get_abi_size(self.target_data, context=self.mod.context) or None
                except Exception:
                    size = None
            elif self.layout_text is not None:
                from . import datalayout
                try:
                    size = datalayout.abi_size(self.llty(ty), self.layout_text) or None
                except TypeError:
                    size = None
            self._abi_sizes[ty] = size
        return self._abi_sizes[ty]

    def expand_args(self, key: str, args: list[ir.Value]) -> list[ir.Value]:
        """exclusive slice parameters are unpacked into (ptr, len) pair."""
        f = self.func_decls.get(key)
        if f is None or not any(self._split(p, self._param_ty(p)) for p in f.params):
            return args
        out: list[ir.Value] = []
        for p, a in zip(f.params, args):
            if self._split(p, self._param_ty(p)):
                out += [self.b.extract_value(a, 0), self.b.extract_value(a, 1)]
            else:
                out.append(a)
        return out

    def _declare_extern(self, d: ExternFuncDecl) -> None:
        args = []
        plans: list[cabi.Plan | None] = []
        attrs: list[tuple[int, str]] = []  # (argument index, attribute) for `byval` and `sret`
        ret = getattr(d, "ret_ty", None) or (d.ret.name if d.ret else "void")
        ret_plan = self._c_plan(ret, d, result=True) if ret in self.program.struct_infos else None
        if ret_plan is not None and ret_plan.how == "sret":
            attrs.append((0, "sret"))
            args.append(self.llty(ret).as_pointer())
        for p in d.params:
            ty = self._param_ty(p)
            plan = self._c_plan(ty, d) if ty in self.program.struct_infos and p.mode not in ("read", "lend") else None
            plans.append(plan)
            if ty == "str":
                args.append(I8P)
            elif plan is not None and plan.how == "direct":
                args.extend(plan.parts)
            elif plan is not None:  # "indirect" or "byval": a pointer to a copy
                if plan.how == "byval":
                    attrs.append((len(args), "byval"))
                args.append(self.llty(ty).as_pointer())
            else:
                lt = self.llty(ty)
                args.append(lt.as_pointer() if p.mode in ("read", "lend") else lt)
        if ret_plan is None:
            rt = I8P if ret == "str" else self.llty(ret)
        else:
            rt = VOID if ret_plan.how == "sret" else ret_plan.coerced
        c_symbol = d.c_symbol or d.name
        if self.wasi and c_symbol in self.WASI_UNSUPPORTED:
            raise CodegenError(f"`{self.WASI_UNSUPPORTED[c_symbol]}` is not available on `wasm32-wasi` (the browser "
                               f"playground has no threads, tasks, or sockets); use `gg run` to run it.")
        key = getattr(d, "lookup_key", None) or d.name
        existing = self.rt.get("c_" + c_symbol)
        if existing is None:
            for prev in self.externs.values():
                if prev.name == c_symbol:
                    existing = prev
                    break
        wasi_real = self.wasi and c_symbol in self.WASI_C_ABI and existing is None
        if wasi_real:
            fn = self._wasi_real(c_symbol, d.variadic)
            self.wasi_declared[fn.name] = (rt, self.WASI_C_ABI[c_symbol][2])
        else:
            fn = existing or ir.Function(self.mod, ir.FunctionType(rt, args, var_arg=d.variadic), c_symbol)
        if existing is None and not wasi_real:
            for i, attr in attrs:
                fn.args[i].add_attribute(attr)
        if getattr(d, "weak", False) and not self.windows and existing is None:
            fn.linkage = "extern_weak"  # missing here: the address is null, and the program does not call it
        self.externs[key] = fn
        if ret_plan is not None or any(plans):
            self.c_plans[fn.name] = (plans, ret_plan, ret)

    def _c_leaves(self, ty: str, base: int = 0) -> list[cabi.Leaf]:
        """The scalars of a C-compatible value with their byte offsets (for the C calling convention)."""
        if ty in ("f32", "f64"):
            return [cabi.Leaf(base, 4 if ty == "f32" else 8, "float" if ty == "f32" else "double")]
        if ty in BITS or ty == "bool" or is_ptr_type(ty) or is_fn_type(ty):
            return [cabi.Leaf(base, self.size_align(ty)[0], "int")]
        if is_array_type(ty):
            n, elem = array_info(ty)
            step = self.size_align(elem)[0]
            return [lf for i in range(n) for lf in self._c_leaves(elem, base + i * step)]
        info = self.program.struct_infos[ty]
        out: list[cabi.Leaf] = []
        off = 0
        for fty in info.fields.values():
            size, al = self.size_align(fty)
            off = (off + al - 1) // al * al
            out.extend(self._c_leaves(fty, base + off))
            off += size
        return out

    def _c_plan(self, ty: str, d: ExternFuncDecl, result: bool = False) -> cabi.Plan:
        size, align = self.size_align(ty)
        leaves = self._c_leaves(ty)
        plan = (cabi.plan_result if result else cabi.plan_param)(leaves, size, align, self.triple)
        if plan is None:
            raise CodegenError(f"`{d.name}` passes the struct `{ty}` by value, which is supported for C on x86-64 "
                               f"and arm64 targets, not on `{self.triple}`. Pass a pointer (`read {ty}`) instead.")
        return plan

    def c_call(self, fn: ir.Function, args: list[ir.Value]) -> ir.Value:
        """Calls a C function whose struct parameters or result follow the platform's C rules."""
        plans, ret_plan, ret_ty = self.c_plans[fn.name]
        b = self.b
        out: list[ir.Value] = []
        sret = None
        if ret_plan is not None and ret_plan.how == "sret":
            sret = self.alloca(self.llty(ret_ty), "c_result")
            out.append(sret)
        for i, v in enumerate(args):
            plan = plans[i] if i < len(plans) else None
            if plan is None:
                out.append(v)
                continue
            slot = self.alloca(v.type, "c_arg")
            b.store(v, slot)
            if plan.how == "direct":
                coerced = b.load(b.bitcast(slot, plan.coerced.as_pointer()))
                if len(plan.parts) == 1:
                    out.append(coerced)
                else:
                    out.extend(b.extract_value(coerced, j) for j in range(len(plan.parts)))
            else:
                out.append(slot)  # a copy only this call sees
        res = b.call(fn, out)
        if sret is not None:
            return b.load(sret)
        if ret_plan is not None:
            slot = self.alloca(self.llty(ret_ty), "c_result")
            b.store(res, b.bitcast(slot, ret_plan.coerced.as_pointer()))
            return b.load(slot)
        return res

    def _emit_main(self, funcs: list[FuncDecl]) -> None:
        user_main = self.funcs.get("main")
        if self.freestanding:
            self._emit_freestanding_libc()
        self._emit_arg_runtime()
        if user_main is None:
            return
        if self.freestanding:
            self._emit_start(user_main)
            return
        fn = ir.Function(self.mod, ir.FunctionType(I32, [I32, I8P.as_pointer()]), "main")
        with self.func_ctx(fn):
            self.b.store(fn.args[0], self._g_argc)
            self.b.store(fn.args[1], self._g_argv)
            if self.leakcheck:
                self.b.call(self.c_fn("atexit", I32, [ir.FunctionType(VOID, []).as_pointer()]),
                            [self.rt_leakcheck()])
            for d, g in self.const_init:
                self.store_expr(d.value, g)
            self.b.call(user_main, [])
            self.b.ret(ir.Constant(I32, 0))
            self.finish_entry()

    # -- freestanding (--no-std / bare-metal) ------------------------------
    def need_os(self, what: str, node: Node | None = None) -> None:
        if self.freestanding:
            where = f" ({self.filename}:{node.line}:{node.col})" if node is not None else ""
            raise CodegenError(f"`{what}` requires an operating system; cannot be used in `--no-std`/`bare-metal` mode{where}.")

    def trap(self) -> None:
        trap = self.rt.get("trap")
        if trap is None:
            trap = ir.Function(self.mod, ir.FunctionType(VOID, []), "llvm.trap")
            self.rt["trap"] = trap
        self.b.call(trap, [])
        self.b.unreachable()

    def _emit_start(self, user_main: ir.Function) -> None:
        """`_start`: libc-free entry point. `exit(0)` syscall on Linux x86_64, infinite loop otherwise."""
        fn = ir.Function(self.mod, ir.FunctionType(VOID, []), "_start")
        with self.func_ctx(fn):
            for d, g in self.const_init:
                self.store_expr(d.value, g)
            self.b.call(user_main, [])
            if self.triple.startswith("wasm"):  # the host called `_start`; returning ends the program
                self.b.ret_void()
            elif "linux" in self.triple and self.triple.startswith("x86_64"):
                asm = ir.FunctionType(VOID, [I64, I64])
                self.b.asm(asm, "syscall", "{rax},{rdi},~{rcx},~{r11},~{memory}",
                           [ir.Constant(I64, 60), ir.Constant(I64, 0)], True)
                self.b.unreachable()
            else:
                loop = self.new_block("halt")
                self.b.branch(loop)
                self.at(loop)
                self.b.branch(loop)
            self.finish_entry()

    def _emit_freestanding_libc(self) -> None:
        """memcpy/memmove/memset/memcmp: emitted freely by LLVM; provided via byte loops if libc absent."""
        sigs = {
            "memcpy": (I8P, [I8P, I8P, I64]), "memmove": (I8P, [I8P, I8P, I64]),
            "memset": (I8P, [I8P, I32, I64]), "memcmp": (I32, [I8P, I8P, I64]),
        }
        for name, (ret, args) in sigs.items():
            fn = self.c_fn(name, ret, args)
            fn.linkage = "weak"
            fn.attributes.add("noinline")
            fn.attributes.add("optnone")
            with self.func_ctx(fn):
                b = self.b
                n = fn.args[2]
                if name in ("memcpy", "memmove"):
                    dst, src = fn.args[0], fn.args[1]
                    back = b.icmp_unsigned(">", dst, src) if name == "memmove" else ir.Constant(I1, 0)
                    fwd, bwd, done = self.new_block("fwd"), self.new_block("bwd"), self.new_block("done")
                    b.cbranch(back, bwd, fwd)
                    self.at(fwd)
                    self.loop_n(n, lambda i: b.store(b.load(b.gep(src, [i])), b.gep(dst, [i])))
                    b.branch(done)
                    self.at(bwd)
                    self.loop_n(n, lambda i: b.store(b.load(b.gep(src, [b.sub(b.sub(n, ir.Constant(I64, 1)), i)])),
                                                     b.gep(dst, [b.sub(b.sub(n, ir.Constant(I64, 1)), i)])))
                    b.branch(done)
                    self.at(done)
                    b.ret(dst)
                elif name == "memset":
                    dst = fn.args[0]
                    byte = b.trunc(fn.args[1], I8)
                    self.loop_n(n, lambda i: b.store(byte, b.gep(dst, [i])))
                    b.ret(dst)
                else:
                    x, y = fn.args[0], fn.args[1]
                    res = self.alloca(I32)
                    b.store(ir.Constant(I32, 0), res)
                    i = self.alloca(I64)
                    b.store(ir.Constant(I64, 0), i)
                    head, body, diff, out = (self.new_block(k) for k in ("h", "b", "d", "o"))
                    b.branch(head)
                    self.at(head)
                    iv = b.load(i)
                    b.cbranch(b.icmp_unsigned("<", iv, n), body, out)
                    self.at(body)
                    a, c = b.load(b.gep(x, [iv])), b.load(b.gep(y, [iv]))
                    b.store(b.add(iv, ir.Constant(I64, 1)), i)
                    b.cbranch(b.icmp_unsigned("==", a, c), head, diff)
                    self.at(diff)
                    b.store(b.sub(b.zext(a, I32), b.zext(c, I32)), res)
                    b.branch(out)
                    self.at(out)
                    b.ret(b.load(res))
                self.finish_entry()

    # -- function context ----------------------------------------------------
    @contextmanager
    def func_ctx(self, fn: ir.Function):
        saved = (self.b, self.entry_b, self.fn, self.vars, self.flags, self.scopes, self.loops, self.yields,
                 self.cur_ret, self.in_main, self.filename, self.vectorize, self.safe_loops, self.len_equiv,
                 self.ref_locals, self.cur_ret_view, self.yield_ptr, self.di_scope)
        self.vectorize = False
        self.di_scope = None
        entry = fn.append_basic_block("entry")
        body = fn.append_basic_block("body")
        self.fn = fn
        self.entry_b = ir.IRBuilder(entry)
        self._body_blk = body
        self.b = ir.IRBuilder(body)
        self.vars, self.flags, self.scopes, self.loops, self.yields = {}, {}, [[]], [], []
        self.safe_loops, self.len_equiv = [], {}
        self.ref_locals = set()
        self.cur_ret_view = False
        self.yield_ptr = False
        try:
            yield
        finally:
            (self.b, self.entry_b, self.fn, self.vars, self.flags, self.scopes, self.loops, self.yields,
             self.cur_ret, self.in_main, self.filename, self.vectorize, self.safe_loops, self.len_equiv,
             self.ref_locals, self.cur_ret_view, self.yield_ptr, self.di_scope) = saved

    def finish_entry(self) -> None:
        self.entry_b.branch(self.fn.blocks[1])

    def alloca(self, lt: ir.Type, name: str = "") -> ir.Value:
        return self.entry_b.alloca(lt, name=name)

    def new_block(self, name: str) -> ir.Block:
        return self.fn.append_basic_block(name)

    def terminated(self) -> bool:
        return self.b.block.is_terminated

    def br(self, blk: ir.Block) -> None:
        if not self.terminated():
            self.b.branch(blk)

    def back_edge(self, head: ir.Block) -> None:
        """Loop back-edge; adds vectorization hint in functions using `exclusive`/`soa`."""
        if self.terminated():
            return
        inst = self.b.branch(head)
        # The hint helps LLVM 14. Newer LLVM (llvmlite 0.45+) decides well by itself, and warns about every
        # loop the hint names that it cannot vectorize.
        if self.vectorize and _old_llvm():
            self._loop_ids += 1
            enable = self.mod.add_metadata([ir.MetaDataString(self.mod, "llvm.loop.vectorize.enable"),
                                            ir.Constant(I1, 1)])
            loop = self.mod.add_metadata([ir.Constant(I32, self._loop_ids)])
            loop.operands = (loop, enable)
            inst.set_metadata("llvm.loop", loop)

    def start_dead(self) -> None:
        self.b.position_at_end(self.new_block("dead"))

    def at(self, blk: ir.Block) -> None:
        self.b.position_at_end(blk)

    # -- C library / runtime ------------------------------------
    # wasm32: `size_t` is 32 bits. The generator asks for i64 sizes, so on `wasm32-wasi` these C functions are
    # called through an internal wrapper that narrows the sizes: (return type, argument types, return is signed).
    WASI_C_ABI = {
        "malloc": (I8P, [I32], False), "realloc": (I8P, [I8P, I32], False),
        "memcmp": (I32, [I8P, I8P, I32], False), "memcpy": (I8P, [I8P, I8P, I32], False),
        "memmove": (I8P, [I8P, I8P, I32], False), "memset": (I8P, [I8P, I32, I32], False),
        "strlen": (I32, [I8P], False), "write": (I32, [I32, I8P, I32], True),
        "calloc": (I8P, [I32, I32], False), "fread": (I32, [I8P, I32, I32, I8P], False),
        "fwrite": (I32, [I8P, I32, I32, I8P], False), "snprintf": (I32, [I8P, I32, I8P], False),
    }

    WASI_UNSUPPORTED = {
        "pthread_create": "std.thread", "makecontext": "std.tasks (async)", "socket": "std.net",
    }

    def _wasi_real(self, name: str, var_arg: bool) -> ir.Function:
        """The C function with its wasm32 signature (declared once, shared with `extern` declarations)."""
        real = self.rt.get("wasi_real_" + name)
        if real is None:
            real_ret, real_args, _signed = self.WASI_C_ABI[name]
            real = self.mod.globals.get(name)
            if real is None:
                real = ir.Function(self.mod, ir.FunctionType(real_ret, real_args, var_arg=var_arg), name)
            self.rt["wasi_real_" + name] = real
        return real

    def _wasi_narrow_call(self, real: ir.Function, args: list[ir.Value], ret: ir.Type, signed: bool) -> ir.Value:
        """Calls `real` with integer arguments cut to its parameter widths; the result is widened to `ret`."""
        b = self.b
        fixed = real.function_type.args
        call_args = [b.trunc(a, ra) if i < len(fixed) and isinstance(ra := fixed[i], ir.IntType)
                     and isinstance(a.type, ir.IntType) and ra.width < a.type.width else a
                     for i, a in enumerate(args)]
        res = b.call(real, call_args)
        rt = real.function_type.return_type
        if isinstance(ret, ir.IntType) and isinstance(rt, ir.IntType) and ret.width > rt.width:
            return b.sext(res, ret) if signed else b.zext(res, ret)
        return res

    def _wasi_c_fn(self, name: str, ret: ir.Type, args: list[ir.Type], var_arg: bool) -> ir.Function:
        real = self._wasi_real(name, var_arg)
        real_ret, real_args, signed = self.WASI_C_ABI[name]
        if var_arg or ([str(a) for a in args] == [str(a) for a in real_args] and str(ret) == str(real_ret)):
            return real  # callers of the variadic ones pass `size_t` as i32 already
        wrap = ir.Function(self.mod, ir.FunctionType(ret, args), "gg_wasi_" + name)
        wrap.linkage = "internal"
        wrap.attributes.add("alwaysinline")
        saved = self.b
        self.b = ir.IRBuilder(wrap.append_basic_block("entry"))
        res = self._wasi_narrow_call(real, list(wrap.args), ret, signed)
        self.b.ret_void() if isinstance(ret, ir.VoidType) else self.b.ret(res)
        self.b = saved
        return wrap

    def c_fn(self, name: str, ret: ir.Type, args: list[ir.Type], var_arg: bool = False) -> ir.Function:
        key = "c_" + name
        fn = self.rt.get(key)
        if fn is None and self.wasi and name in self.WASI_C_ABI:
            fn = self._wasi_c_fn(name, ret, args, var_arg)
        if fn is None and name in self.externs:  # user declared same C function with `extern`
            fn = self.externs[name]
        if fn is None:
            for prev in self.externs.values():  # keyed by `module::name`; the IR name is the C symbol
                if prev.name == name:
                    fn = prev
                    break
        if fn is None:
            fn = ir.Function(self.mod, ir.FunctionType(ret, args, var_arg=var_arg), name)
        self.rt[key] = fn
        return fn

    def _runtime(self, name: str, ret: ir.Type, args: list[ir.Type], attrs: tuple[str, ...] = ()) -> tuple[ir.Function, bool]:
        fn = self.rt.get(name)
        if fn is not None:
            return fn, False
        fn = ir.Function(self.mod, ir.FunctionType(ret, args), "gg_rt_" + name)
        fn.linkage = "internal"
        for a in attrs:
            fn.attributes.add(a)
        self.rt[name] = fn
        return fn, True

    def rt_counter(self) -> ir.GlobalVariable:
        g = self.rt.get("counter")
        if g is None:
            g = ir.GlobalVariable(self.mod, I64, "gg_live_allocs")
            g.linkage = "internal"
            g.initializer = ir.Constant(I64, 0)
            self.rt["counter"] = g  # type: ignore[assignment]
        return g  # type: ignore[return-value]

    def count_allocs(self, delta: ir.Value, sub: bool = False) -> None:
        """Adds to (or subtracts from) the live-block counter. Atomic when leak checking is on, because
        threads allocate and free at the same time and a plain load/store would lose updates."""
        cnt = self.rt_counter()
        if self.leakcheck:
            self.b.atomic_rmw("sub" if sub else "add", cnt, delta, "monotonic")
        else:
            cur = self.b.load(cnt)
            self.b.store(self.b.sub(cur, delta) if sub else self.b.add(cur, delta), cnt)

    def _emit_text(self, text_ptr_fn: Callable[[], None]) -> None:
        text_ptr_fn()

    def rt_fail(self, msg: str, args: list[ir.Value] | None = None, fmt: str | None = None) -> None:
        """Writes and exits: `Runtime error: ...` to stderr + exit(101). Operates on current builder."""
        if self.freestanding:  # no libc: trap directly instead of error
            self.trap()
            return
        b = self.b
        buf = b.alloca(ir.ArrayType(I8, 512))
        bufp = b.bitcast(buf, I8P)
        snprintf = self.c_fn("snprintf", I32, [I8P, self.size_t, I8P], var_arg=True)
        n = b.call(snprintf, [bufp, ir.Constant(self.size_t, 512), self.cstr(fmt or ("Runtime error: %s\n")),
                              *(args or [self.cstr(msg)])])
        b.call(self.c_fn("fflush", I32, [I8P]), [ir.Constant(I8P, None)])
        wr = self.c_fn("_write" if self.windows else "write", I32 if self.windows else I64,
                       [I32, I8P, I32 if self.windows else I64])
        cnt = n if self.windows else b.sext(n, I64)
        cnt = b.select(b.icmp_signed(">", n, ir.Constant(I32, 511)), ir.Constant(cnt.type, 511), cnt)
        b.call(wr, [ir.Constant(I32, 2), bufp, cnt])
        b.call(self.c_fn("exit", VOID, [I32]), [ir.Constant(I32, 101)])
        b.unreachable()

    def rt_panic(self) -> ir.Function:
        fn, new = self._runtime("panic", VOID, [I8P, I8P, I32, I32], ("noreturn", "cold"))
        if new:
            with self.func_ctx(fn):
                msg, file, line, col = fn.args
                self.rt_fail("", [msg, file, line, col],
                             "Runtime error: %s\n  --> %s:%d:%d\n")
                self.finish_entry()
        return fn

    def rt_panic_text(self) -> ir.Function:
        """`panic(f"...")`: the message is a (length, bytes) view, not NUL-terminated."""
        fn, new = self._runtime("panic_text", VOID, [I32, I8P, I8P, I32, I32], ("noreturn", "cold"))
        if new:
            with self.func_ctx(fn):
                self.rt_fail("", list(fn.args), "Runtime error: %.*s\n  --> %s:%d:%d\n")
                self.finish_entry()
        return fn

    def rt_panic_bounds(self) -> ir.Function:
        fn, new = self._runtime("panic_bounds", VOID, [I64, I64, I8P, I32, I32], ("noreturn", "cold"))
        if new:
            with self.func_ctx(fn):
                self.rt_fail("", list(fn.args),
                             "Runtime error: array index out of bounds (index %lld, length %lld)\n  --> %s:%d:%d\n")
                self.finish_entry()
        return fn

    def rt_panic_slice(self) -> ir.Function:
        fn, new = self._runtime("panic_slice", VOID, [I64, I64, I64, I8P, I32, I32], ("noreturn", "cold"))
        if new:
            with self.func_ctx(fn):
                self.rt_fail("", list(fn.args),
                             "Runtime error: slice range out of bounds (range %lld..%lld, length %lld)\n  --> %s:%d:%d\n")
                self.finish_entry()
        return fn

    def rt_leakcheck(self) -> ir.Function:
        fn, new = self._runtime("leakcheck", VOID, [])
        if new:
            with self.func_ctx(fn):
                n = self.b.load(self.rt_counter())
                leak, done = self.new_block("leak"), self.new_block("done")
                self.b.cbranch(self.b.icmp_signed("!=", n, ir.Constant(I64, 0)), leak, done)
                self.at(leak)
                buf = self.b.bitcast(self.b.alloca(ir.ArrayType(I8, 128)), I8P)
                k = self.b.call(self.c_fn("snprintf", I32, [I8P, self.size_t, I8P], var_arg=True),
                                [buf, ir.Constant(self.size_t, 128), self.cstr("LEAK: %lld block(s) not freed\n"), n])
                wr = self.c_fn("_write" if self.windows else "write", I32 if self.windows else I64,
                               [I32, I8P, I32 if self.windows else I64])
                self.b.call(wr, [ir.Constant(I32, 2), buf, k if self.windows else self.b.sext(k, I64)])
                self.b.branch(done)
                self.at(done)
                self.b.ret_void()
                self.finish_entry()
        return fn

    def user_allocator(self, role: int) -> ir.Function | None:
        """The program's `allocator` function for alloc (0), resize (1), or free (2), if it has one."""
        keys = getattr(self.program, "allocator", None)
        if not keys:
            return None
        return self.funcs[func_cname(keys[role]) if "::" in keys[role] else keys[role]]

    def rt_alloc(self) -> ir.Function:
        if self.user_allocator(0) is None:
            self.need_os("Box/List (heap)")
        fn, new = self._runtime("alloc", I8P, [I64])
        if new:
            with self.func_ctx(fn):
                n = self.b.select(self.b.icmp_unsigned("==", fn.args[0], ir.Constant(I64, 0)),
                                  ir.Constant(I64, 1), fn.args[0])
                user = self.user_allocator(0)
                p = self.b.call(user if user is not None else self.c_fn("malloc", I8P, [I64]), [n])
                self._null_check(p)
                self.count_allocs(ir.Constant(I64, 1))
                self.b.ret(p)
                self.finish_entry()
        return fn

    def _null_check(self, p: ir.Value) -> None:
        bad, ok = self.new_block("oom"), self.new_block("ok")
        self.b.cbranch(self.b.icmp_unsigned("==", p, ir.Constant(I8P, None)), bad, ok)
        self.at(bad)
        self.rt_fail("out of memory")
        self.at(ok)

    def rt_realloc(self) -> ir.Function:
        if self.user_allocator(1) is None:
            self.need_os("List (heap)")
        fn, new = self._runtime("realloc", I8P, [I8P, I64])
        if new:
            with self.func_ctx(fn):
                old, n = fn.args
                n = self.b.select(self.b.icmp_unsigned("==", n, ir.Constant(I64, 0)), ir.Constant(I64, 1), n)
                user = self.user_allocator(1)
                p = self.b.call(user if user is not None else self.c_fn("realloc", I8P, [I8P, I64]), [old, n])
                self._null_check(p)
                was_null = self.b.icmp_unsigned("==", old, ir.Constant(I8P, None))
                self.count_allocs(self.b.zext(was_null, I64))
                self.b.ret(p)
                self.finish_entry()
        return fn

    def rt_free(self) -> ir.Function:
        if self.user_allocator(2) is None:
            self.need_os("Box/List (heap)")
        fn, new = self._runtime("free", VOID, [I8P])
        if new:
            with self.func_ctx(fn):
                nz, done = self.new_block("nz"), self.new_block("done")
                self.b.cbranch(self.b.icmp_unsigned("!=", fn.args[0], ir.Constant(I8P, None)), nz, done)
                self.at(nz)
                self.count_allocs(ir.Constant(I64, 1), sub=True)
                user = self.user_allocator(2)
                self.b.call(user if user is not None else self.c_fn("free", VOID, [I8P]), [fn.args[0]])
                self.b.branch(done)
                self.at(done)
                self.b.ret_void()
                self.finish_entry()
        return fn

    def rt_str_eq(self) -> ir.Function:
        st = self.llty("str")
        fn, new = self._runtime("str_eq", I1, [st, st])
        if new:
            with self.func_ctx(fn):
                a, c = fn.args
                la, lb = self.b.extract_value(a, 1), self.b.extract_value(c, 1)
                same, cmp, no, end = (self.new_block(n) for n in ("same", "cmp", "no", "end"))
                self.b.cbranch(self.b.icmp_unsigned("==", la, lb), same, no)
                self.at(same)
                self.b.cbranch(self.b.icmp_unsigned("==", la, ir.Constant(I64, 0)), end, cmp)
                self.at(cmp)
                r = self.b.call(self.c_fn("memcmp", I32, [I8P, I8P, I64]),
                                [self.b.extract_value(a, 0), self.b.extract_value(c, 0), la])
                res = self.b.icmp_signed("==", r, ir.Constant(I32, 0))
                self.b.ret(res)
                self.at(end)
                self.b.ret(ir.Constant(I1, 1))
                self.at(no)
                self.b.ret(ir.Constant(I1, 0))
                self.finish_entry()
        return fn

    def rt_str_cmp(self) -> ir.Function:
        """-1, 0, or 1: the first differing byte decides, then the shorter text comes first."""
        st = self.llty("str")
        fn, new = self._runtime("str_cmp", I32, [st, st])
        if new:
            with self.func_ctx(fn):
                a, c = fn.args
                la, lb = self.b.extract_value(a, 1), self.b.extract_value(c, 1)
                n = self.b.select(self.b.icmp_unsigned("<", la, lb), la, lb)
                cmp, by_len = self.new_block("cmp"), self.new_block("by_len")
                self.b.cbranch(self.b.icmp_unsigned("==", n, ir.Constant(I64, 0)), by_len, cmp)
                self.at(cmp)
                r = self.b.call(self.c_fn("memcmp", I32, [I8P, I8P, I64]),
                                [self.b.extract_value(a, 0), self.b.extract_value(c, 0), n])
                differ = self.new_block("differ")
                self.b.cbranch(self.b.icmp_signed("!=", r, ir.Constant(I32, 0)), differ, by_len)
                self.at(differ)
                self.b.ret(self.b.select(self.b.icmp_signed("<", r, ir.Constant(I32, 0)), ir.Constant(I32, -1),
                                         ir.Constant(I32, 1)))
                self.at(by_len)
                lt = self.b.zext(self.b.icmp_unsigned("<", la, lb), I32)
                gt = self.b.zext(self.b.icmp_unsigned(">", la, lb), I32)
                self.b.ret(self.b.sub(gt, lt))
                self.finish_entry()
        return fn

    def rt_input(self) -> ir.Function:
        self.need_os("input")
        st = self.llty("str")
        fn, new = self._runtime("input", st, [st])
        if new:
            slots = ir.GlobalVariable(self.mod, ir.ArrayType(ir.ArrayType(I8, 1024), 16), "gg_stdin_buffers")
            slots.linkage = "internal"
            slots.initializer = ir.Constant(slots.value_type, None)
            slot = ir.GlobalVariable(self.mod, I64, "gg_stdin_slot")
            slot.linkage = "internal"
            slot.initializer = ir.Constant(I64, 0)
            with self.func_ctx(fn):
                b = self.b
                prompt = fn.args[0]
                plen = b.extract_value(prompt, 1)
                has, go = self.new_block("prompt"), self.new_block("read")
                b.cbranch(b.icmp_unsigned(">", plen, ir.Constant(I64, 0)), has, go)
                self.at(has)
                b.call(self.c_fn("printf", I32, [I8P], var_arg=True),
                       [self.cstr("%.*s"), b.trunc(plen, I32), b.extract_value(prompt, 0)])
                b.call(self.c_fn("fflush", I32, [I8P]), [ir.Constant(I8P, None)])
                b.branch(go)
                self.at(go)
                idx = b.load(slot)
                buf = b.gep(slots, [ir.Constant(I32, 0), idx, ir.Constant(I32, 0)], inbounds=True)
                b.store(b.urem(b.add(idx, ir.Constant(I64, 1)), ir.Constant(I64, 16)), slot)
                n = self.alloca(I64)
                b.store(ir.Constant(I64, 0), n)
                head, body, add, fin = (self.new_block(x) for x in ("head", "body", "add", "fin"))
                b.branch(head)
                self.at(head)
                ln = b.load(n)
                b.cbranch(b.icmp_unsigned("<", ln, ir.Constant(I64, 1023)), body, fin)
                self.at(body)
                c = b.call(self.c_fn("getchar", I32, []), [])
                skip = self.new_block("cr")
                chk = self.new_block("chk")
                b.cbranch(b.or_(b.icmp_signed("<", c, ir.Constant(I32, 0)), b.icmp_signed("==", c, ir.Constant(I32, 10))),
                          fin, chk)
                self.at(chk)
                b.cbranch(b.icmp_signed("==", c, ir.Constant(I32, 13)), skip, add)
                self.at(skip)
                b.branch(head)
                self.at(add)
                b.store(b.trunc(c, I8), b.gep(buf, [ln], inbounds=True))
                b.store(b.add(ln, ir.Constant(I64, 1)), n)
                b.branch(head)
                self.at(fin)
                ln = b.load(n)
                b.store(ir.Constant(I8, 0), b.gep(buf, [ln], inbounds=True))
                res = ir.Constant(st, ir.Undefined)
                res = b.insert_value(res, buf, 0)
                res = b.insert_value(res, ln, 1)
                b.ret(res)
                self.finish_entry()
        return fn

    # -- drop ----------------------------------------------------------
    def drop_fn(self, ty: str) -> ir.Function:
        fn = self.drops.get(ty)
        if fn is not None:
            return fn
        fn = ir.Function(self.mod, ir.FunctionType(VOID, [self.llty(ty)]), "gg_drop_" + self._ident(ty))
        fn.linkage = "internal"
        self.drops[ty] = fn
        with self.func_ctx(fn):
            b = self.b
            v = fn.args[0]
            hk = heap_kind(ty)
            if hk == "Box":
                inner = heap_inner(ty)
                p = b.extract_value(v, 0)
                if self.nd(inner):
                    nz, done = self.new_block("nz"), self.new_block("done")
                    b.cbranch(b.icmp_unsigned("!=", p, ir.Constant(p.type, None)), nz, done)
                    self.at(nz)
                    b.call(self.drop_fn(inner), [b.load(p)])
                    b.branch(done)
                    self.at(done)
                b.call(self.rt_free(), [b.bitcast(p, I8P)])
            elif is_dyn_type(ty):  # the table's first entry drops the concrete value and frees it
                data = b.extract_value(v, 0)
                nz, done = self.new_block("nz"), self.new_block("done")
                b.cbranch(b.icmp_unsigned("!=", data, ir.Constant(I8P, None)), nz, done)
                self.at(nz)
                dropper = b.bitcast(b.load(b.extract_value(v, 1)), ir.FunctionType(VOID, [I8P]).as_pointer())
                b.call(dropper, [data])
                b.branch(done)
                self.at(done)
            elif is_boxed_fn(ty):  # last owner of the environment runs its dropper and frees it
                env = b.extract_value(v, 1)
                nz, last, done = self.new_block("nz"), self.new_block("last"), self.new_block("done")
                b.cbranch(b.icmp_unsigned("!=", env, ir.Constant(I8P, None)), nz, done)
                self.at(nz)
                hdr = b.bitcast(env, self.env_header().as_pointer())
                cp = b.gep(hdr, [ir.Constant(I32, 0), ir.Constant(I32, 0)], inbounds=True)
                n = b.sub(b.load(cp), ir.Constant(I64, 1))
                b.store(n, cp)
                b.cbranch(b.icmp_unsigned("==", n, ir.Constant(I64, 0)), last, done)
                self.at(last)
                dropper = b.load(b.gep(hdr, [ir.Constant(I32, 0), ir.Constant(I32, 1)], inbounds=True))
                has, skip = self.new_block("has"), self.new_block("skip")
                b.cbranch(b.icmp_unsigned("!=", dropper, ir.Constant(dropper.type, None)), has, skip)
                self.at(has)
                b.call(dropper, [env])
                b.branch(skip)
                self.at(skip)
                b.call(self.rt_free(), [env])
                b.branch(done)
                self.at(done)
            elif hk in ("Shared", "Arc"):  # last owner frees the value
                inner = heap_inner(ty)
                p = b.extract_value(v, 0)
                nz, last, done = self.new_block("nz"), self.new_block("last"), self.new_block("done")
                b.cbranch(b.icmp_unsigned("!=", p, ir.Constant(p.type, None)), nz, done)
                self.at(nz)
                cp = b.gep(p, [ir.Constant(I32, 0), ir.Constant(I32, 0)], inbounds=True)
                if hk == "Arc":  # acq_rel: the last owner sees every write made before the other drops
                    n = b.sub(b.atomic_rmw("sub", cp, ir.Constant(I64, 1), "acq_rel"), ir.Constant(I64, 1))
                else:
                    n = b.sub(b.load(cp), ir.Constant(I64, 1))
                    b.store(n, cp)
                b.cbranch(b.icmp_unsigned("==", n, ir.Constant(I64, 0)), last, done)
                self.at(last)
                if self.nd(inner):
                    b.call(self.drop_fn(inner), [b.load(b.gep(p, [ir.Constant(I32, 0), ir.Constant(I32, 1)],
                                                              inbounds=True))])
                b.call(self.rt_free(), [b.bitcast(p, I8P)])
                b.branch(done)
                self.at(done)
            elif hk == "List":
                inner = heap_inner(ty)
                p = b.extract_value(v, 0)
                if self.nd(inner):
                    n = b.extract_value(v, 1)
                    self.loop_n(n, lambda i: b.call(self.drop_fn(inner), [b.load(b.gep(p, [i], inbounds=True))]))
                b.call(self.rt_free(), [b.bitcast(p, I8P)])
            elif is_array_type(ty):  # each element in place
                n, elem = array_info(ty)
                slot = b.alloca(v.type)
                b.store(v, slot)
                self.loop_n(ir.Constant(I64, n), lambda i: b.call(self.drop_fn(elem), [b.load(
                    b.gep(slot, [ir.Constant(I32, 0), i], inbounds=True))]))
            elif ty in self.program.struct_infos:
                info = self.program.struct_infos[ty]
                if info.user_drop:  # the destructor sees the whole value, then the fields are freed
                    v = self.call_user_drop(ty, v)
                for i, (fname, fty) in enumerate(info.fields.items()):
                    if fname not in info.field_modes and self.nd(fty):
                        b.call(self.drop_fn(fty), [b.extract_value(v, i)])
            else:
                info = self.program.enum_infos[ty]
                if info.user_drop:
                    v = self.call_user_drop(ty, v)
                slot = b.alloca(self.llty(ty))
                b.store(v, slot)
                tag = b.load(b.gep(slot, [ir.Constant(I32, 0), ir.Constant(I32, 0)]))
                for vi, (vname, vinfo) in enumerate(info.variants.items()):
                    parts = [(j, pt) for j, pt in enumerate(vinfo.payload) if self.nd(pt)]
                    if not parts:
                        continue
                    yes, nxt = self.new_block("v"), self.new_block("n")
                    b.cbranch(b.icmp_signed("==", tag, ir.Constant(I32, vi)), yes, nxt)
                    self.at(yes)
                    for j, pt in parts:
                        b.call(self.drop_fn(pt), [b.load(self.payload_ptr(slot, ty, vname, j))])
                    b.branch(nxt)
                    self.at(nxt)
            b.ret_void()
            self.finish_entry()
        return fn

    def call_user_drop(self, ty: str, v: ir.Value) -> ir.Value:
        """Runs `ty.drop(self: lend Self)` on `v` and returns the value as `drop` left it."""
        b = self.b
        slot = b.alloca(self.llty(ty))
        b.store(v, slot)
        b.call(self.funcs[func_cname(f"{ty}.drop")], [slot])
        return b.load(slot)

    @staticmethod
    def is_temp(e: Expr) -> bool:
        """True for a fresh owned value (a call, `f"..."`, `a + b`); False for a place or a view of one."""
        if isinstance(e, (Name, FieldAccess, IndexAccess, SliceExpr, BorrowExpr)):
            return False
        return not getattr(e, "is_view", False) and not getattr(e, "view_ptr", False)

    def clone_val(self, v: ir.Value, ty: str) -> ir.Value:
        """Deep copy of a value: heap parts get new allocations, everything else is copied."""
        return self.b.call(self.clone_fn(ty), [v]) if self.nd(ty) else v

    def clone_fn(self, ty: str) -> ir.Function:
        fn = self.clones.get(ty)
        if fn is not None:
            return fn
        lt = self.llty(ty)
        fn = ir.Function(self.mod, ir.FunctionType(lt, [lt]), "gg_clone_" + self._ident(ty))
        fn.linkage = "internal"
        self.clones[ty] = fn
        with self.func_ctx(fn):
            b = self.b
            v = fn.args[0]
            hk = heap_kind(ty)
            if hk == "Box":
                inner = heap_inner(ty)
                it = self.llty(inner)
                p = b.extract_value(v, 0)
                nz, null = self.new_block("nz"), self.new_block("null")
                b.cbranch(b.icmp_unsigned("!=", p, ir.Constant(p.type, None)), nz, null)
                self.at(null)
                b.ret(v)
                self.at(nz)
                q = b.bitcast(b.call(self.rt_alloc(), [self.sizeof(it)]), it.as_pointer())
                b.store(self.clone_val(b.load(p), inner), q)
                b.ret(b.insert_value(v, q, 0))
            elif is_boxed_fn(ty):
                env = b.extract_value(v, 1)
                nz, done = self.new_block("nz"), self.new_block("done")
                b.cbranch(b.icmp_unsigned("!=", env, ir.Constant(I8P, None)), nz, done)
                self.at(nz)
                cp = b.gep(b.bitcast(env, self.env_header().as_pointer()), [ir.Constant(I32, 0), ir.Constant(I32, 0)],
                           inbounds=True)
                b.store(b.add(b.load(cp), ir.Constant(I64, 1)), cp)
                b.branch(done)
                self.at(done)
                b.ret(v)
            elif hk in ("Shared", "Arc"):
                p = b.extract_value(v, 0)
                nz, done = self.new_block("nz"), self.new_block("done")
                b.cbranch(b.icmp_unsigned("!=", p, ir.Constant(p.type, None)), nz, done)
                self.at(nz)
                cp = b.gep(p, [ir.Constant(I32, 0), ir.Constant(I32, 0)], inbounds=True)
                if hk == "Arc":
                    b.atomic_rmw("add", cp, ir.Constant(I64, 1), "monotonic")
                else:
                    b.store(b.add(b.load(cp), ir.Constant(I64, 1)), cp)
                b.branch(done)
                self.at(done)
                b.ret(v)
            elif hk == "List":
                inner = heap_inner(ty)
                it = self.llty(inner)
                p, n = b.extract_value(v, 0), b.extract_value(v, 1)
                empty, full = self.new_block("empty"), self.new_block("full")
                b.cbranch(b.icmp_unsigned("==", n, ir.Constant(I64, 0)), empty, full)
                self.at(empty)
                b.ret(ir.Constant(lt, None))
                self.at(full)
                q = b.bitcast(b.call(self.rt_alloc(), [b.mul(n, self.sizeof(it))]), it.as_pointer())
                self.loop_n(n, lambda i: b.store(self.clone_val(b.load(b.gep(p, [i], inbounds=True)), inner),
                                                 b.gep(q, [i], inbounds=True)))
                out = b.insert_value(ir.Constant(lt, ir.Undefined), q, 0)
                out = b.insert_value(out, n, 1)
                b.ret(b.insert_value(out, n, 2))
            elif is_array_type(ty):
                n, elem = array_info(ty)
                src, dst = b.alloca(lt), b.alloca(lt)
                b.store(v, src)
                self.loop_n(ir.Constant(I64, n), lambda i: b.store(
                    self.clone_val(b.load(b.gep(src, [ir.Constant(I32, 0), i], inbounds=True)), elem),
                    b.gep(dst, [ir.Constant(I32, 0), i], inbounds=True)))
                b.ret(b.load(dst))
            elif ty in self.program.struct_infos:
                info = self.program.struct_infos[ty]
                out = v
                for i, (fname, fty) in enumerate(info.fields.items()):
                    if fname not in info.field_modes and self.nd(fty):
                        out = b.insert_value(out, self.clone_val(b.extract_value(v, i), fty), i)
                b.ret(out)
            else:
                info = self.program.enum_infos[ty]
                src, dst = b.alloca(lt), b.alloca(lt)
                b.store(v, src)
                b.store(v, dst)
                tag = b.load(b.gep(src, [ir.Constant(I32, 0), ir.Constant(I32, 0)]))
                for vi, (vname, vinfo) in enumerate(info.variants.items()):
                    parts = [(j, pt) for j, pt in enumerate(vinfo.payload) if self.nd(pt)]
                    if not parts:
                        continue
                    yes, nxt = self.new_block("v"), self.new_block("n")
                    b.cbranch(b.icmp_signed("==", tag, ir.Constant(I32, vi)), yes, nxt)
                    self.at(yes)
                    for j, pt in parts:
                        val = b.load(self.payload_ptr(src, ty, vname, j))
                        b.store(self.clone_val(val, pt), self.payload_ptr(dst, ty, vname, j))
                    b.branch(nxt)
                    self.at(nxt)
                b.ret(b.load(dst))
            self.finish_entry()
        return fn

    def vec_edit(self, e: MethodCall, op: str) -> ir.Value:
        """`swap(i, j)`, `swap_remove(i)`, `remove(i)`, `insert(i, x)` on a list (bounds-checked)."""
        b = self.b
        lst = self.addr(e.obj)
        f_ptr, f_len = (b.gep(lst, [ir.Constant(I32, 0), ir.Constant(I32, k)], inbounds=True) for k in range(2))
        idx = [self.to_i64(self.expr(a), a.ty) for a in (e.args[:1] if op == "insert" else e.args)]
        n = b.load(f_len)
        one = ir.Constant(I64, 1)

        def at(i: ir.Value) -> ir.Value:
            return b.gep(b.load(f_ptr), [i], inbounds=True)

        def move(src: ir.Value, dst: ir.Value) -> None:
            b.store(b.load(at(src)), at(dst))

        if op == "swap":
            i, j = idx
            if not self.unchecked:
                self._bounds(i, n, e.args[0])
                self._bounds(j, n, e.args[1])
            tmp = b.load(at(i))
            move(j, i)
            b.store(tmp, at(j))
            return ir.Constant(I32, 0)
        if op == "swap_remove":
            i = idx[0]
            self._bounds(i, n, e.args[0])  # always checked: the element is moved out
            out = b.load(at(i))
            last = b.sub(n, one)
            move(last, i)
            b.store(last, f_len)
            return out
        if op == "remove":
            i = idx[0]
            self._bounds(i, n, e.args[0])
            out = b.load(at(i))
            last = b.sub(n, one)
            self.loop_range(i, last, lambda k: move(b.add(k, one), k))
            b.store(last, f_len)
            return out
        # insert: append, then rotate the new element down to `i`
        i = idx[0]
        self._bounds(i, b.add(n, one), e.args[0])
        x = self.expr(e.args[1])
        b.call(self.vec_fn(e.owner or "", "push"), [lst, x])
        tmp = b.load(at(n))
        top = b.add(n, i)  # k = i .. n-1 shifts slot (n + i - k - 1) up to (n + i - k)
        self.loop_range(i, n, lambda k: move(b.sub(top, b.add(k, one)), b.sub(top, k)))
        b.store(tmp, at(i))
        return ir.Constant(I32, 0)

    def loop_range(self, lo: ir.Value, hi: ir.Value, body: Callable[[ir.Value], Any]) -> None:
        """for (k = lo; k < hi; ++k) body(k)  -- i64 bounds"""
        b = self.b
        k = self.alloca(I64)
        b.store(lo, k)
        head, bod, done = self.new_block("rh"), self.new_block("rb"), self.new_block("rd")
        b.branch(head)
        self.at(head)
        kv = b.load(k)
        b.cbranch(b.icmp_unsigned("<", kv, hi), bod, done)
        self.at(bod)
        body(kv)
        b.store(b.add(kv, ir.Constant(I64, 1)), k)
        b.branch(head)
        self.at(done)

    def loop_n(self, n: ir.Value, body: Callable[[ir.Value], Any]) -> None:
        """for (i = 0; i < n; ++i) body(i)  -- n: i64"""
        b = self.b
        i = self.alloca(I64)
        b.store(ir.Constant(I64, 0), i)
        head, bod, done = self.new_block("lh"), self.new_block("lb"), self.new_block("ld")
        b.branch(head)
        self.at(head)
        iv = b.load(i)
        b.cbranch(b.icmp_unsigned("<", iv, n), bod, done)
        self.at(bod)
        body(iv)
        b.store(b.add(iv, ir.Constant(I64, 1)), i)
        b.branch(head)
        self.at(done)

    def payload_ptr(self, enum_ptr: ir.Value, ety: str, variant: str, idx: int) -> ir.Value:
        """Pointer to `idx`-th field of `variant` payload in enum value."""
        info = self.program.enum_infos[ety]
        payload = list(info.variants[variant].payload)
        raw = self.b.gep(enum_ptr, [ir.Constant(I32, 0), ir.Constant(I32, 1)], inbounds=True)
        sp = self.b.bitcast(raw, self.payload_type(payload).as_pointer())
        return self.b.gep(sp, [ir.Constant(I32, 0), ir.Constant(I32, idx)], inbounds=True)

    @staticmethod
    def tag_index(info: EnumInfo, variant: str) -> int:
        return list(info.variants).index(variant)

    # -- List -----------------------------------------------------------
    def sizeof(self, lt: ir.Type) -> ir.Value:
        one = self.b.gep(ir.Constant(lt.as_pointer(), None), [ir.Constant(I32, 1)])
        return self.b.ptrtoint(one, I64)

    def overflow_intrinsic(self, name: str) -> ir.Function:
        """`llvm.<name>.with.overflow.i64`, e.g. `uadd`: the result and whether it overflowed."""
        iname = f"llvm.{name}.with.overflow.i64"
        fn = self.mod.globals.get(iname)
        if fn is None:
            fn = ir.Function(self.mod, ir.FunctionType(ir.LiteralStructType([I64, I1]), [I64, I64]), iname)
        return fn

    def vec_fn(self, ty: str, op: str) -> ir.Function:
        key = (ty, op)
        fn = self.vec_fns.get(key)
        if fn is not None:
            return fn
        inner = heap_inner(ty)
        vt, it = self.llty(ty), self.llty(inner)
        if op == "push":
            ft = ir.FunctionType(VOID, [vt.as_pointer(), it])
        elif op == "pop":
            ft = ir.FunctionType(self.llty(f"Optional[{inner}]"), [vt.as_pointer()])
        elif op in ("reserve", "truncate"):
            ft = ir.FunctionType(VOID, [vt.as_pointer(), I64])
        elif op == "resize":
            ft = ir.FunctionType(VOID, [vt.as_pointer(), I64, it])
        elif op == "push_str":
            ft = ir.FunctionType(VOID, [vt.as_pointer(), self.llty("str")])
        else:
            ft = ir.FunctionType(VOID, [vt.as_pointer()])
        fn = ir.Function(self.mod, ft, f"gg_{self._ident(ty)}_{op}")
        fn.linkage = "internal"
        self.vec_fns[key] = fn
        with self.func_ctx(fn):
            b = self.b
            v = fn.args[0]
            f_ptr, f_len, f_cap = (b.gep(v, [ir.Constant(I32, 0), ir.Constant(I32, k)], inbounds=True) for k in range(3))
            if op == "push":
                ln = b.load(f_len)
                ln.set_metadata("range", self.range_meta_i64_pos())
                cap = b.load(f_cap)
                grow, cont = self.new_block("grow"), self.new_block("cont")
                b.cbranch(b.icmp_unsigned("==", ln, cap), grow, cont)
                self.at(grow)
                ncap = b.select(b.icmp_unsigned("==", cap, ir.Constant(I64, 0)), ir.Constant(I64, 4),
                                b.mul(cap, ir.Constant(I64, 2)))
                raw = b.call(self.rt_realloc(), [b.bitcast(b.load(f_ptr), I8P), b.mul(ncap, self.sizeof(it))])
                b.store(b.bitcast(raw, it.as_pointer()), f_ptr)
                b.store(ncap, f_cap)
                b.branch(cont)
                self.at(cont)
                ln = b.load(f_len)
                ln.set_metadata("range", self.range_meta_i64_pos())
                b.store(fn.args[1], b.gep(b.load(f_ptr), [ln], inbounds=True))
                b.store(b.add(ln, ir.Constant(I64, 1)), f_len)
                b.ret_void()
            elif op == "pop":
                oty = f"Optional[{inner}]"
                res = b.alloca(self.llty(oty))
                oinfo = self.program.enum_infos[oty]
                ln = b.load(f_len)
                ln.set_metadata("range", self.range_meta_i64_pos())
                some, none = self.new_block("some"), self.new_block("none")
                b.cbranch(b.icmp_unsigned("==", ln, ir.Constant(I64, 0)), none, some)
                self.at(none)
                b.store(ir.Constant(I32, self.tag_index(oinfo, "None")), b.gep(res, [ir.Constant(I32, 0), ir.Constant(I32, 0)]))
                b.ret(b.load(res))
                self.at(some)
                nl = b.sub(ln, ir.Constant(I64, 1))
                b.store(nl, f_len)
                b.store(ir.Constant(I32, self.tag_index(oinfo, "Valid")), b.gep(res, [ir.Constant(I32, 0), ir.Constant(I32, 0)]))
                b.store(b.load(b.gep(b.load(f_ptr), [nl], inbounds=True)), self.payload_ptr(res, oty, "Valid", 0))
                b.ret(b.load(res))
            elif op == "reserve":
                # Room for `n` more elements in one allocation: max(len + n, 2 * cap), as `push` would reach.
                # A size that does not fit 64 bits becomes all ones, so the allocation fails and reports it.
                ln, cap = b.load(f_len), b.load(f_cap)
                ln.set_metadata("range", self.range_meta_i64_pos())
                add = b.call(self.overflow_intrinsic("uadd"), [ln, fn.args[1]])
                need = b.extract_value(add, 0)
                grow, done = self.new_block("grow"), self.new_block("done")
                b.cbranch(b.or_(b.icmp_unsigned(">", need, cap), b.extract_value(add, 1)), grow, done)
                self.at(grow)
                twice = b.mul(cap, ir.Constant(I64, 2))
                ncap = b.select(b.icmp_unsigned(">", need, twice), need, twice)
                mul = b.call(self.overflow_intrinsic("umul"), [ncap, self.sizeof(it)])
                bad = b.or_(b.extract_value(add, 1), b.extract_value(mul, 1))
                size = b.select(bad, ir.Constant(I64, -1), b.extract_value(mul, 0))
                raw = b.call(self.rt_realloc(), [b.bitcast(b.load(f_ptr), I8P), size])
                b.store(b.bitcast(raw, it.as_pointer()), f_ptr)
                b.store(ncap, f_cap)
                b.branch(done)
                self.at(done)
                b.ret_void()
            elif op == "truncate":  # keep the first `n` elements; a longer `n` changes nothing
                ln = b.load(f_len)
                ln.set_metadata("range", self.range_meta_i64_pos())
                keep = b.select(b.icmp_unsigned("<", ln, fn.args[1]), ln, fn.args[1])
                if self.nd(inner):
                    p = b.load(f_ptr)
                    self.loop_n(b.sub(ln, keep), lambda i: b.call(
                        self.drop_fn(inner), [b.load(b.gep(p, [b.add(keep, i)], inbounds=True))]))
                b.store(keep, f_len)
                b.ret_void()
            elif op == "resize":  # length `n`: cut the tail, or append copies of `x`
                ln = b.load(f_len)
                ln.set_metadata("range", self.range_meta_i64_pos())
                grow, done = self.new_block("grow"), self.new_block("done")
                b.cbranch(b.icmp_unsigned(">", fn.args[1], ln), grow, done)
                self.at(done)
                b.store(fn.args[1], f_len)  # shorter or equal: elements are copies, nothing to drop
                b.ret_void()
                self.at(grow)
                extra = b.sub(fn.args[1], ln)
                b.call(self.vec_fn(ty, "reserve"), [v, extra])
                dst = b.gep(b.load(f_ptr), [ln], inbounds=True)
                if isinstance(it, ir.IntType) and it.width == 8:
                    b.call(self.c_fn("memset", I8P, [I8P, I32, I64]),
                           [b.bitcast(dst, I8P), b.zext(fn.args[2], I32), extra])
                else:
                    self.loop_n(extra, lambda i: b.store(fn.args[2], b.gep(dst, [i], inbounds=True)))
                b.store(fn.args[1], f_len)
                b.ret_void()
            elif op == "push_str":  # `List[u8]`: the bytes of a `str`, copied at once
                text = fn.args[1]
                n = b.extract_value(text, 1)
                copy, done = self.new_block("copy"), self.new_block("done")
                b.cbranch(b.icmp_unsigned("==", n, ir.Constant(I64, 0)), done, copy)
                self.at(done)
                b.ret_void()
                self.at(copy)
                b.call(self.vec_fn(ty, "reserve"), [v, n])
                ln = b.load(f_len)
                ln.set_metadata("range", self.range_meta_i64_pos())
                dst = b.gep(b.load(f_ptr), [ln], inbounds=True)
                b.call(self.c_fn("memcpy", I8P, [I8P, I8P, I64]), [dst, b.extract_value(text, 0), n])
                b.store(b.add(ln, n), f_len)
                b.ret_void()
            else:  # clear
                if self.nd(inner):
                    p = b.load(f_ptr)
                    self.loop_n(b.load(f_len), lambda i: b.call(self.drop_fn(inner), [b.load(b.gep(p, [i], inbounds=True))]))
                b.store(ir.Constant(I64, 0), f_len)
                b.ret_void()
            self.finish_entry()
        return fn

    # -- function bodies -----------------------------------------------------
    def _define_func(self, f: FuncDecl) -> None:
        fn = self.funcs[self.fname(f)]
        self.in_main_flag = f.name == "main" and f.owner is None
        with self.func_ctx(fn):
            self.in_main = f.name == "main" and f.owner is None
            self.cur_func_overflow = getattr(f, "overflow_mode", None)
            mark_bounded_counters(f)
            self.wrapping_depth = 0
            if f.from_prelude:
                self.filename = "<prelude>"
            elif getattr(f, "filename", None):
                self.filename = f.filename  # type: ignore[assignment]
            self.cur_ret = getattr(f, "ret_ty", None) or (f.ret.name if f.ret else "void")
            self.cur_ret_view = bool(getattr(f, "ret_view", False))
            if self.di is not None:
                shown = f"{f.owner.replace('::', '.')}.{f.name}" if f.owner else f.name
                self.di_scope = self.di.subprogram(fn, shown, getattr(f, "filename", None) or self.filename, f.line)
                start = self.di.location(f.line, f.col, self.di_scope)
                self.b.debug_metadata = start
                self.entry_b.debug_metadata = start
            self.vectorize = (any(getattr(p, "exclusive", False) for p in f.params)
                              or any(isinstance(n, VarDecl) and n.is_soa for n in _walk(f.body)))
            ai = 0
            for p in f.params:
                ty = self._param_ty(p)
                if self._split(p, ty):
                    ptr = fn.args[ai]
                    ln = fn.args[ai + 1]
                    ai += 2
                    self.vars[p.name] = SliceVal(ptr, ln)
                    continue
                else:
                    arg = fn.args[ai]
                    ai += 1
                if is_slice_type(ty):
                    ptr = self.b.extract_value(arg, 0)
                    ln = self.b.extract_value(arg, 1)
                    self.vars[p.name] = SliceVal(ptr, ln, arg)
                    continue
                if self._by_ptr(p, ty):
                    self.vars[p.name] = arg
                else:
                    slot = self.alloca(self.llty(ty), p.name)
                    self.b.store(arg, slot)
                    self.vars[p.name] = slot
                    self.dbg_var(slot, p.name, ty, f.line)
                    if p.mode == "consume" and self.nd(ty):
                        self.own(p.name, ty)
            self.body(f.body, new_scope=False)
            if not self.terminated():
                self.emit_drops(0)
                if self.in_main or self.cur_ret == "void":
                    self.b.ret_void()
                else:
                    self.b.unreachable()
            self.finish_entry()

    def own(self, name: str, ty: str) -> None:
        flag = self.alloca(I1, f"live.{name}")
        self.b.store(ir.Constant(I1, 1), flag)
        self.flags[name] = flag
        self.scopes[-1].append((name, ty, self.vars[name], flag))

    def emit_drops(self, from_depth: int) -> None:
        """Drops owners in scopes from `from_depth` upwards (inside out); does not modify stack."""
        for scope in reversed(self.scopes[from_depth:]):
            for name, ty, ptr, flag in reversed(scope):
                if name == "@defer":
                    self.stmt(ty)
                    continue
                yes, nxt = self.new_block("drop"), self.new_block("kept")
                self.b.cbranch(self.b.load(flag), yes, nxt)
                self.at(yes)
                self.b.call(self.drop_fn(ty), [self.b.load(ptr)])
                self.b.branch(nxt)
                self.at(nxt)

    def has_owned(self, from_depth: int = 0) -> bool:
        return any(scope for scope in self.scopes[from_depth:])

    def body(self, stmts: list[Stmt], new_scope: bool = True) -> None:
        saved_vars, saved_flags = dict(self.vars), dict(self.flags)
        if new_scope:
            self.scopes.append([])
        for s in stmts:
            self.stmt(s)
        if new_scope:
            if self.scopes[-1] and not self.terminated():
                self.emit_drops(len(self.scopes) - 1)
            self.scopes.pop()
            self.vars, self.flags = saved_vars, saved_flags

    # -- deyimler -----------------------------------------------------------
    def dbg_var(self, slot: ir.Value, name: str, ty: str | None, line: int) -> None:
        """Names a local for the debugger (see `debuginfo` for the types it describes)."""
        if self.di is None or self.di_scope is None or not ty or name.startswith("__"):
            return
        ditype = self.di.type_of(ty, self)
        if ditype is not None:
            self.di.declare(self.b, slot, name, ditype, self.di_scope, self.filename, line,
                            self.b.debug_metadata or self.di.location(line, 0, self.di_scope))

    def stmt(self, s: Stmt) -> None:
        if self.di is not None and self.di_scope is not None and getattr(s, "line", 0):
            self.b.debug_metadata = self.di.location(s.line, s.col, self.di_scope)
        prev, self.cur_stmt = self.cur_stmt, s
        try:
            self._stmt(s)
        finally:
            self.cur_stmt = prev

    def _stmt(self, s: Stmt) -> None:
        if isinstance(s, VarDecl) and s.is_soa:
            assert s.ty is not None
            n, sty = array_info(s.ty)
            info = self.program.struct_infos[sty]
            fields = {}
            for fname, fty in info.fields.items():
                at = ir.ArrayType(self.llty(fty), n)
                slot = self.alloca(at, f"{s.name}.{fname}")
                self.b.store(ir.Constant(at, None), slot)
                fields[fname] = slot
            self.vars[s.name] = SoaVar(sty, n, fields)  # type: ignore[assignment]
        elif isinstance(s, VarDecl):
            assert s.ty is not None
            if s.ref_mode:
                slot = self.alloca(self.llty(s.ty).as_pointer(), s.name)
                self.b.store(self.addr(s.value), slot)
                self.vars[s.name] = slot
                self.ref_locals.add(s.name)
            else:
                slot = self.alloca(self.llty(s.ty), s.name)
                self.store_expr(s.value, slot)
                self.vars[s.name] = slot
                self.dbg_var(slot, s.name, s.ty, s.line)
                if self.nd(s.ty):
                    self.own(s.name, s.ty)
        elif isinstance(s, Assign):
            self.assign(s)
        elif isinstance(s, ExprStmt):
            self.expr_stmt(s.expr)
        elif isinstance(s, Return):
            self.do_return(s)
        elif isinstance(s, Defer):
            self.scopes[-1].append(("@defer", s.stmt, None, None))
        elif isinstance(s, Yield):
            val = self.addr(s.value) if self.yield_ptr else self.expr(s.value)
            self.b.store(val, self.yields[-1])
        elif isinstance(s, Pass):
            pass
        elif isinstance(s, Match):
            self.match(s)
        elif isinstance(s, (Break, Continue)):
            brk, cont, depth = self.loops[-1]
            if self.has_owned(depth):
                self.emit_drops(depth)
            self.b.branch(brk if isinstance(s, Break) else cont)
            self.start_dead()
        elif isinstance(s, If):
            self.if_stmt(s)
        elif isinstance(s, While):
            head, bod, done = self.new_block("wh"), self.new_block("wb"), self.new_block("wd")
            self.b.branch(head)
            self.at(head)
            self.b.cbranch(self.expr(s.cond), bod, done)
            self.at(bod)
            self.loops.append((done, head, len(self.scopes)))
            self.body(s.body)
            self.loops.pop()
            self.back_edge(head)
            self.at(done)
        elif isinstance(s, For):
            self.for_stmt(s)
        elif isinstance(s, ForIn):
            self.for_in(s)
        elif isinstance(s, Require):
            self.require_stmt(s)
        elif isinstance(s, Wrapping):
            self.wrapping_depth += 1
            self.body(s.body)
            self.wrapping_depth -= 1
        elif isinstance(s, OverflowMode):
            self.cur_func_overflow = s.mode
        else:
            raise CodegenError(f"beklenmeyen deyim: {type(s).__name__}")

    def require_stmt(self, s: Require) -> None:
        if isinstance(s.cond, Binary) and s.cond.op == "==":
            l, r = s.cond.left, s.cond.right
            if (isinstance(l, FieldAccess) and l.field_name == "len" and isinstance(l.obj, Name) and
                isinstance(r, FieldAccess) and r.field_name == "len" and isinstance(r.obj, Name)):
                n1, n2 = l.obj.name, r.obj.name
                eq1 = self.get_len_equivalences(n1)
                eq2 = self.get_len_equivalences(n2)
                merged = eq1 | eq2
                for name in merged:
                    self.len_equiv[name] = merged
        c = s.cond
        if (isinstance(c, Binary) and c.op in COMPARE and getattr(c, "overload", None) is None
                and not self.freestanding and self.scalar_spec(c.left.ty) and self.scalar_spec(c.right.ty)):
            # `require a == b`: the failure shows both operands, evaluated once
            l, rv = self.expr(c.left), self.expr(c.right)
            bad = self.b.not_(self.compare(c.op, c.left.ty or "i32", l, rv))
            self.fail_if(bad, lambda: self.require_failed(s, [(c.left.ty or "", l), (c.right.ty or "", rv)]))
            return
        v = self.expr(c)
        bad = self.b.not_(v)
        self.fail_if(bad, lambda: self.panic_call(
            "require condition failed" + ("" if self.freestanding else f": {unparse(c)}"), s.line, s.col))

    def scalar_spec(self, ty: str | None) -> str | None:
        """printf conversion for a number, `bool`, or `str`; None for any other type."""
        ty = int_base(ty or "")
        return {"i8": "%d", "i16": "%d", "i32": "%d", "u8": "%u", "u16": "%u", "u32": "%u",
                "i64": "%lld", "isize": "%lld", "u64": "%llu", "usize": "%llu", "f32": "%g", "f64": "%.15g",
                "bool": "%s", "str": "%.*s"}.get(ty)

    def scalar_args(self, ty: str, v: ir.Value) -> list[ir.Value]:
        """printf arguments for `scalar_spec(ty)`."""
        b = self.b
        ty = int_base(ty)
        if ty in ("i8", "i16"):
            return [b.sext(v, I32)]
        if ty in ("u8", "u16"):
            return [b.zext(v, I32)]
        if ty == "f32":
            return [b.fpext(v, F64)]
        if ty == "bool":
            return [b.select(v, self.cstr("true"), self.cstr("false"))]
        if ty == "str":
            return [b.trunc(b.extract_value(v, 1), I32), b.extract_value(v, 0)]
        return [v]

    def require_failed(self, s: Require, operands: list[tuple[str, ir.Value]]) -> None:
        """Formats `require condition failed: a == b (left: 3, right: 5)` and panics with it."""
        b = self.b
        text = unparse(s.cond).replace("%", "%%")
        quote = ['"' if ty == "str" else "" for ty, _ in operands]
        fmt = (f"require condition failed: {text} (left: {quote[0]}{self.scalar_spec(operands[0][0])}{quote[0]}, "
               f"right: {quote[1]}{self.scalar_spec(operands[1][0])}{quote[1]})")
        args = [a for ty, v in operands for a in self.scalar_args(ty, v)]
        buf = b.bitcast(self.alloca(ir.ArrayType(I8, 512)), I8P)
        sn = self.c_fn("snprintf", I32, [I8P, self.size_t, I8P], var_arg=True)
        b.call(sn, [buf, ir.Constant(self.size_t, 512), self.cstr(fmt), *args])
        call = b.call(self.rt_panic(), [buf, self.cstr(self.filename), ir.Constant(I32, s.line), ir.Constant(I32, s.col)])
        call.attributes.add("noreturn")

    def do_return(self, s: Return) -> None:
        val = None
        if s.value is not None and not self.in_main:
            val = self.addr(s.value) if self.cur_ret_view else self.expr(s.value)
            if self.cur_ret is not None:
                ret_llty = self.llty(self.cur_ret)
                if isinstance(val.type, ir.IntType) and isinstance(ret_llty, ir.IntType) and val.type != ret_llty:
                    val = self.cast(val, f"i{val.type.width}", f"i{ret_llty.width}")
        if self.has_owned():
            self.emit_drops(0)
        if self.in_main or s.value is None or self.cur_ret == "void":
            self.b.ret_void()
        else:
            self.b.ret(val)
        self.start_dead()

    def soa_of(self, e: Expr) -> SoaVar | None:
        """If `e` is an element of an `soa` array (`p[i]`), returns that array."""
        if isinstance(e, IndexAccess) and isinstance(e.obj, Name):
            v = self.vars.get(e.obj.name)
            if isinstance(v, SoaVar):
                return v
        return None

    def soa_index(self, sv: SoaVar, e: IndexAccess) -> ir.Value:
        idx = self.to_i64(self.expr(e.index), e.index.ty)
        if not self.unchecked and not self._is_check_eliminated(e):
            self._bounds(idx, ir.Constant(I64, sv.n), e)
        return idx

    def soa_gather(self, sv: SoaVar, e: IndexAccess) -> ir.Value:
        idx = self.soa_index(sv, e)
        res = ir.Constant(self.llty(sv.sty), ir.Undefined)
        for i, fname in enumerate(self.program.struct_infos[sv.sty].fields):
            p = self.b.gep(sv.fields[fname], [ir.Constant(I32, 0), idx], inbounds=True)
            res = self.b.insert_value(res, self.b.load(p), i)
        return res

    def assign(self, s: Assign) -> None:
        ty = s.target.ty or "i32"
        sv = self.soa_of(s.target)
        if sv is not None:
            if s.op != "=":
                raise CodegenError("cannot perform compound assignment to soa element; modify field instead (`p[i].x += 1`).")
            val = self.expr(s.value)
            idx = self.soa_index(sv, s.target)  # type: ignore[arg-type]
            for i, fname in enumerate(self.program.struct_infos[sv.sty].fields):
                self.b.store(self.b.extract_value(val, i),
                             self.b.gep(sv.fields[fname], [ir.Constant(I32, 0), idx], inbounds=True))
            return
        if s.op == "=" and getattr(s, "rebind", False):
            ptr_val = self.addr(s.value)
            if isinstance(s.target, Name) and s.target.name in self.ref_locals:
                self.b.store(ptr_val, self.vars[s.target.name])
            elif isinstance(s.target, FieldAccess):
                self.b.store(ptr_val, self._field_slot(s.target))
            else:
                self.b.store(ptr_val, self.place(s.target))
            return
        if s.op == "=":
            if self.nd(ty):
                new = self.expr(s.value)
                ptr = self.place(s.target)
                flag = self.flags.get(s.target.name) if isinstance(s.target, Name) else None
                if flag is not None:
                    yes, nxt = self.new_block("old"), self.new_block("set")
                    self.b.cbranch(self.b.load(flag), yes, nxt)
                    self.at(yes)
                    self.b.call(self.drop_fn(ty), [self.b.load(ptr)])
                    self.b.branch(nxt)
                    self.at(nxt)
                    self.b.store(ir.Constant(I1, 1), flag)
                else:
                    self.b.call(self.drop_fn(ty), [self.b.load(ptr)])
                self.b.store(new, ptr)
            else:
                ptr = self.place(s.target)
                v = self.expr(s.value)
                target_ty = ptr.type.pointee
                if isinstance(v.type, ir.IntType) and isinstance(target_ty, ir.IntType) and v.type != target_ty:
                    v = self.cast(v, f"i{v.type.width}", f"i{target_ty.width}")
                self.b.store(v, ptr)
            return
        ptr = self.place(s.target)
        rhs = self.expr(s.value)
        cur = self.b.load(ptr)
        if getattr(s, "in_range", False):  # counters.py proved the sum fits `ty`
            if isinstance(rhs.type, ir.IntType) and rhs.type != cur.type:
                rhs = self.cast(rhs, f"i{rhs.type.width}", f"i{cur.type.width}")
            self.b.store(self.b.add(cur, rhs, flags=["nsw" if ty in SIGNED else "nuw"]), ptr)
            return
        self.b.store(self.arith(s.op[:-1], ty, cur, rhs, s.line, s.col, s.value.ty), ptr)

    def expr_stmt(self, e: Expr) -> None:
        v = self.expr(e)
        if isinstance(e, Try):
            if self.nd(e.ty):
                self.b.call(self.drop_fn(e.ty), [v])  # type: ignore[arg-type]
        elif (isinstance(e, (Call, MethodCall)) and e.ty not in (None, "void") and self.nd(e.ty)
              and not getattr(e, "is_view", False)):
            self.b.call(self.drop_fn(e.ty), [v])  # type: ignore[arg-type]

    def platform_cond(self, e: Expr) -> bool | None:
        """The value of a condition made only of `target_os() == "..."` / `target_arch()` tests, `and`, `or`,
        and `not`, or None. Such a branch is decided here, so code for another platform is not emitted and
        does not need its functions to link."""
        if isinstance(e, Unary) and e.op == "not":
            v = self.platform_cond(e.operand)
            return None if v is None else not v
        if isinstance(e, Binary) and e.op in ("and", "or"):
            a, b = self.platform_cond(e.left), self.platform_cond(e.right)
            if a is None or b is None:
                return None
            return (a and b) if e.op == "and" else (a or b)
        if isinstance(e, Binary) and e.op in ("==", "!="):
            for call, lit in ((e.left, e.right), (e.right, e.left)):
                kind = getattr(call, "builtin", None)
                if kind in ("target_os", "target_arch") and isinstance(lit, StrLit):
                    here = target_os(self.triple) if kind == "target_os" else target_arch(self.triple)
                    return (here == lit.value) == (e.op == "==")
        return None

    def if_stmt(self, s: If) -> None:
        end = self.new_block("endif")
        for br in s.branches:
            known = self.platform_cond(br.cond)
            if known is False:
                continue
            if known is True:
                self.body(br.body)
                self.br(end)
                self.at(end)
                return
            then, nxt = self.new_block("then"), self.new_block("else")
            self.b.cbranch(self.expr(br.cond), then, nxt)
            self.at(then)
            self.body(br.body)
            self.br(end)
            self.at(nxt)
        if s.else_body is not None:
            self.body(s.else_body)
        self.br(end)
        self.at(end)

    def _get_safe_loop_collection(self, s: For) -> set[str] | None:
        if not (isinstance(s.start, IntLit) and s.start.value == 0 and s.step_value == 1 and not s.inclusive):
            return None
        if isinstance(s.end, FieldAccess) and s.end.field_name == "len" and isinstance(s.end.obj, Name):
            return self.get_len_equivalences(s.end.obj.name)
        return None

    def _is_check_eliminated(self, e: IndexAccess) -> bool:
        if getattr(e, "trusted", False):
            return True
        ity = getattr(e.index, "ty", None)
        oty = getattr(e.obj, "ty", None)
        if ity and is_bounded_int(ity) and oty and is_array_type(oty):
            _, lo, hi = bounded_int_info(ity)
            n, _ = array_info(oty)
            if lo >= 0 and hi <= n:
                return True
        if not isinstance(e.index, Name):
            return False
        idx_var = e.index.name
        if not isinstance(e.obj, Name):
            return False
        coll_name = e.obj.name
        for loop_var, colls in reversed(self.safe_loops):
            if loop_var == idx_var and coll_name in colls:
                return True
        return False

    def for_stmt(self, s: For) -> None:
        assert s.var_ty is not None
        lt = self.llty(s.var_ty)
        signed = s.var_ty in SIGNED
        cmp = self.b.icmp_signed if signed else self.b.icmp_unsigned
        var = self.alloca(lt, s.var)
        end = self.alloca(lt, s.var + ".end")
        self.b.store(self.expr(s.start), var)
        self.b.store(self.expr(s.end), end)
        step = s.step_value
        desc = step < 0
        done_f = self.alloca(I1) if (s.inclusive or step != 1) else None
        if done_f is not None:
            self.b.store(ir.Constant(I1, 0), done_f)
        head, bod, inc, out = (self.new_block(n) for n in ("fh", "fb", "fi", "fo"))
        self.b.branch(head)
        self.at(head)
        cur, lim = self.b.load(var), self.b.load(end)
        ok = cmp((">" if desc else "<") + ("=" if s.inclusive else ""), cur, lim)
        if done_f is not None:
            ok = self.b.and_(ok, self.b.not_(self.b.load(done_f)))
        self.b.cbranch(ok, bod, out)
        self.at(bod)
        saved = self.vars.get(s.var)
        self.vars[s.var] = var
        self.loops.append((out, inc, len(self.scopes)))
        safe_coll = self._get_safe_loop_collection(s)
        if safe_coll:
            self.safe_loops.append((s.var, safe_coll))
        self.body(s.body)
        if safe_coll:
            self.safe_loops.pop()
        self.loops.pop()
        self.br(inc)
        self.at(inc)
        cur = self.b.load(var)
        one = ir.Constant(lt, 1)
        if step != 1:
            lim = self.b.load(end)
            diff = self.b.sub(cur, lim) if desc else self.b.sub(lim, cur)
            fin = self.b.icmp_unsigned("<" if s.inclusive else "<=", diff, ir.Constant(lt, abs(step)))
            self.b.store(fin, done_f)
            self.b.store(self.b.select(fin, cur, self.b.add(cur, ir.Constant(lt, step))), var)
        elif s.inclusive:
            fin = self.b.icmp_unsigned("==", cur, self.b.load(end))
            self.b.store(fin, done_f)
            self.b.store(self.b.select(fin, cur, self.b.add(cur, one)), var)
        else:
            self.b.store(self.b.add(cur, one), var)
        self.back_edge(head)
        self.at(out)
        if saved is not None:
            self.vars[s.var] = saved
        else:
            self.vars.pop(s.var, None)

    def for_in(self, s: ForIn) -> None:
        assert s.elem_ty is not None
        if s.count:  # `for i in N:` -> `for i in 0..N:`
            zero = IntLit(0, line=s.line, col=s.col)
            zero.ty = s.elem_ty
            self.for_stmt(For(s.var, zero, s.iterable, False, s.body, var_ty=s.elem_ty, line=s.line, col=s.col))
            return
        if self._fused_words(s):
            return
        ity = s.iterable.ty or ""
        if is_array_type(ity):
            n, _ = array_info(ity)
            base = self.b.gep(self.addr(s.iterable), [ir.Constant(I32, 0), ir.Constant(I32, 0)], inbounds=True)
            count: ir.Value = ir.Constant(I64, n)
        elif is_slice_type(ity) and isinstance(s.iterable, Name) and s.iterable.name in self.vars and isinstance(self.vars[s.iterable.name], SliceVal):
            sv = self.vars[s.iterable.name]
            base, count = sv.ptr, sv.len
        else:
            sl = self.base_val(s.iterable)  # a fresh list (`for x in make():`) is freed after the loop
            base, count = self.b.extract_value(sl, 0), self.b.extract_value(sl, 1)
        var = None if s.by_ref else self.alloca(self.llty(s.elem_ty), s.var)
        idx = self.alloca(I64, s.index_var or "")
        self.b.store(ir.Constant(I64, 0), idx)
        head, bod, inc, out = (self.new_block(n) for n in ("ih", "ib", "ii", "io"))
        self.b.branch(head)
        self.at(head)
        i = self.b.load(idx)
        self.b.cbranch(self.b.icmp_unsigned("<", i, count), bod, out)
        self.at(bod)
        elem_ptr = self.b.gep(base, [i], inbounds=True)
        if s.by_ref:
            var = elem_ptr  # loop variable is the address of the element itself
        else:
            self.b.store(self.b.load(elem_ptr), var)
        saved = self.vars.get(s.var)
        self.vars[s.var] = var
        saved_idx = self.vars.get(s.index_var) if s.index_var else None
        if s.index_var:
            self.vars[s.index_var] = idx
        self.loops.append((out, inc, len(self.scopes)))
        has_safe = False
        if s.index_var and isinstance(s.iterable, Name):
            self.safe_loops.append((s.index_var, self.get_len_equivalences(s.iterable.name)))
            has_safe = True
        self.body(s.body)
        if has_safe:
            self.safe_loops.pop()
        self.loops.pop()
        self.br(inc)
        self.at(inc)
        self.b.store(self.b.add(self.b.load(idx), ir.Constant(I64, 1)), idx)
        self.back_edge(head)
        self.at(out)
        for name, old in ((s.var, saved), (s.index_var, saved_idx)):
            if name is None:
                continue
            if old is not None:
                self.vars[name] = old
            else:
                self.vars.pop(name, None)

    def is_space_byte(self, c: ir.Value) -> ir.Value:
        """`c` is ' ', '\\t', '\\n' or '\\r' (core's `_is_space`), without branches: bit `c` of a mask."""
        b = self.b
        wide = b.zext(c, I64)
        small = b.icmp_unsigned("<=", wide, ir.Constant(I64, 32))
        bits = b.lshr(ir.Constant(I64, (1 << 9) | (1 << 10) | (1 << 13) | (1 << 32)),
                      b.select(small, wide, ir.Constant(I64, 0)))
        return b.and_(small, b.trunc(bits, I1))

    def _fused_words(self, s: ForIn) -> bool:
        """`for w in text.split_whitespace():` walks the words of `text` directly instead of building the list
        first. Same words, same order, same `break`/`continue`; the type checker already checked the loop
        against the list, whose views borrow `text` the same way."""
        it = s.iterable
        if not (isinstance(it, MethodCall) and it.method == "split_whitespace" and not it.args
                and getattr(it, "builtin", None) is None and it.owner == "str" and (it.obj.ty or "") == "str"
                and s.index_var is None and not s.mutable and s.elem_ty == "str"):
            return False
        decl = self.func_decls.get(func_cname(getattr(it, "method_key", None) or "str.split_whitespace"))
        if decl is None or not getattr(decl, "from_prelude", False):
            return False
        b = self.b
        text = self.expr(it.obj)
        base, n = b.extract_value(text, 0), b.extract_value(text, 1)
        idx, start = self.alloca(I64, "word_at"), self.alloca(I64, "word_start")
        var = self.alloca(self.llty("str"), s.var)
        b.store(ir.Constant(I64, 0), idx)
        head, gap, gap_chk, word, word_chk, word_end, bod, out = (self.new_block(x) for x in (
            "wh", "wgap", "wgapc", "wword", "wwordc", "wend", "wbody", "wout"))
        b.branch(head)
        self.at(head)  # also the `continue` target: the position already moved past the last word
        b.cbranch(b.icmp_unsigned("<", b.load(idx), n), gap, out)
        self.at(gap)  # skip the spaces before a word
        i = b.load(idx)
        b.cbranch(b.icmp_unsigned("<", i, n), gap_chk, word)
        self.at(gap_chk)
        sp = self.is_space_byte(b.load(b.gep(base, [i], inbounds=True)))
        nxt = self.new_block("wgapn")
        b.cbranch(sp, nxt, word)
        self.at(nxt)
        b.store(b.add(i, ir.Constant(I64, 1)), idx)
        b.branch(gap)
        self.at(word)
        b.store(b.load(idx), start)
        b.branch(word_chk)
        self.at(word_chk)  # the word runs to the next space or the end
        i = b.load(idx)
        more, step = self.new_block("wwordm"), self.new_block("wwordn")
        b.cbranch(b.icmp_unsigned("<", i, n), more, word_end)
        self.at(more)
        sp = self.is_space_byte(b.load(b.gep(base, [i], inbounds=True)))
        b.cbranch(sp, word_end, step)
        self.at(step)
        b.store(b.add(i, ir.Constant(I64, 1)), idx)
        b.branch(word_chk)
        self.at(word_end)
        i, st = b.load(idx), b.load(start)
        b.cbranch(b.icmp_unsigned(">", i, st), bod, out)  # no word: only spaces were left
        self.at(bod)
        w = ir.Constant(self.llty("str"), ir.Undefined)
        w = b.insert_value(w, b.gep(base, [st], inbounds=True), 0)
        b.store(b.insert_value(w, b.sub(i, st), 1), var)
        saved = self.vars.get(s.var)
        self.vars[s.var] = var
        self.loops.append((out, head, len(self.scopes)))
        self.body(s.body)
        self.loops.pop()
        self.back_edge(head)
        self.at(out)
        if saved is not None:
            self.vars[s.var] = saved
        else:
            self.vars.pop(s.var, None)
        return True

    def pat_cond(self, p: Node, ty: str, val: ir.Value) -> ir.Value:
        """Condition for one scalar pattern (literal or range) against value `val`."""
        if isinstance(p, RangePat):
            lo, hi = self.expr(p.lo), self.expr(p.hi)
            return self.b.and_(self.compare("<=", ty, lo, val), self.compare("<=" if p.inclusive else "<", ty, val, hi))
        return self.compare("==", ty, val, self.expr(p))  # type: ignore[arg-type]

    def match_scalar(self, s: Match) -> None:
        """`match` on integer / char / bool / string: chain of comparisons."""
        ty = s.scalar_ty
        assert ty is not None
        val = self.expr(s.scrutinee)
        end = self.new_block("mend")
        whole = None
        if any(arm.whole is not None for arm in s.arms):
            whole = self.alloca(val.type, "match_value")
            self.b.store(val, whole)
        for i, arm in enumerate(s.arms):
            last = i == len(s.arms) - 1
            blk = self.new_block("arm")
            nxt = None
            if arm.guard is not None:
                nxt = end if last else self.new_block("next")
            if last or not arm.pats:
                self.b.branch(blk)
            else:
                nxt = nxt or self.new_block("next")
                cond = None
                for p in arm.pats:
                    c = self.pat_cond(p, ty, val)
                    cond = c if cond is None else self.b.or_(cond, c)
                self.b.cbranch(cond, blk, nxt)
            self.at(blk)
            if arm.guard is not None:
                self.guard(arm, nxt, lambda j: None, whole)
            saved_vars, saved_flags = dict(self.vars), dict(self.flags)
            self.scopes.append([])
            if arm.whole is not None:
                self.vars[arm.whole] = whole
            for st in arm.body:
                self.stmt(st)
            if self.scopes[-1] and not self.terminated():
                self.emit_drops(len(self.scopes) - 1)
            self.scopes.pop()
            self.vars, self.flags = saved_vars, saved_flags
            self.br(end)
            if nxt is None:
                break
            if nxt is not end:
                self.at(nxt)
        self.at(end)

    def guard(self, arm: "MatchArm", fail: ir.Block, member: Callable[[int], ir.Value], whole: ir.Value | None) -> None:
        """`pattern if cond:`: evaluates `cond` with the bindings pointing into the matched value (nothing is
        moved yet) and jumps to `fail` when it is false. Temporaries of the guard are freed before the jump."""
        saved_vars, saved_flags = dict(self.vars), dict(self.flags)
        self.scopes.append([])
        for j, bnd in enumerate(arm.bindings):
            if bnd.name != "_":
                self.vars[bnd.name] = member(j)
        if arm.whole is not None:
            self.vars[arm.whole] = whole
        ok = self.expr(arm.guard)
        if self.scopes[-1]:
            self.emit_drops(len(self.scopes) - 1)
        self.scopes.pop()
        self.vars, self.flags = saved_vars, saved_flags
        go = self.new_block("guard_ok")
        self.b.cbranch(ok, go, fail)
        self.at(go)

    def match(self, s: Match) -> None:
        if s.scalar_ty is not None:
            self.match_scalar(s)
            return
        assert s.enum_ty is not None
        ety = s.enum_ty
        info = self.program.enum_infos[ety]
        lt = self.llty(ety)
        if s.mode == "lend":
            slot = self.addr(s.scrutinee)
        else:
            slot = self.alloca(lt)
            self.b.store(self.expr(s.scrutinee), slot)
        give_drop = s.mode == "consume" and self.nd(ety)
        temp_drop = (s.mode == "" and self.nd(ety) and not isinstance(s.scrutinee, (Name, FieldAccess, IndexAccess))
                     and not getattr(s.scrutinee, "is_view", False))
        if give_drop and isinstance(s.scrutinee, Name) and s.scrutinee.name in self.flags:
            self.b.store(ir.Constant(I1, 0), self.flags[s.scrutinee.name])
        if temp_drop:  # a scope of its own, so a `return` or `break` in an arm frees it too
            live = self.alloca(I1, "live.tmp")
            self.entry_b.store(ir.Constant(I1, 0), live)
            self.b.store(ir.Constant(I1, 1), live)
            self.scopes.append([("@temp", ety, slot, live)])
        tag = self.b.load(self.b.gep(slot, [ir.Constant(I32, 0), ir.Constant(I32, 0)], inbounds=True))
        end = self.new_block("mend")
        for i, arm in enumerate(s.arms):
            last = i == len(s.arms) - 1
            blk = self.new_block("arm")
            if not last or arm.guard is not None:
                nxt = self.new_block("next") if not last else end
            if last or arm.variant is None:
                self.b.branch(blk)
            else:
                self.b.cbranch(self.b.icmp_signed("==", tag, ir.Constant(I32, self.tag_index(info, arm.variant or ""))),
                               blk, nxt)
            self.at(blk)
            if arm.guard is not None:  # the payload as views while the guard runs; ownership only if it holds
                self.guard(arm, nxt, lambda j: self.payload_ptr(slot, ety, arm.variant or "", j), slot)
            saved_vars, saved_flags = dict(self.vars), dict(self.flags)
            self.scopes.append([])
            if arm.whole is not None:
                self.vars[arm.whole] = slot
            if give_drop and arm.variant is None:
                self.b.call(self.drop_fn(ety), [self.b.load(slot)])
            for j, b in enumerate(arm.bindings):
                pty = arm.payload_tys[j]
                member = self.payload_ptr(slot, ety, arm.variant or "", j)
                if b.name == "_":
                    if give_drop and self.nd(pty):
                        self.b.call(self.drop_fn(pty), [self.b.load(member)])
                    continue
                if s.mode == "lend":
                    self.vars[b.name] = member
                else:
                    var = self.alloca(self.llty(pty), b.name)
                    self.b.store(self.b.load(member), var)
                    self.vars[b.name] = var
                    if give_drop and self.nd(pty):
                        self.own(b.name, pty)
            for st in arm.body:
                self.stmt(st)
            if self.scopes[-1] and not self.terminated():
                self.emit_drops(len(self.scopes) - 1)
            self.scopes.pop()
            self.vars, self.flags = saved_vars, saved_flags
            self.br(end)
            if not last:
                self.at(nxt)
        self.at(end)
        if temp_drop:
            if not self.terminated():
                self.emit_drops(len(self.scopes) - 1)
            self.scopes.pop()

    # -- yer (adreslenebilir) ifadeler -------------------------------------
    def is_place(self, e: Expr) -> bool:
        if isinstance(e, BorrowExpr):
            return True
        if getattr(e, "view_ptr", False) and isinstance(e, (Call, MethodCall, BlockExpr)):
            return True
        if isinstance(e, FieldAccess):
            return e.ctor_enum is None
        if isinstance(e, Name):
            if e.ctor_enum is not None or getattr(e, "func_ref", False):
                return False
            v = self.vars.get(e.name)
            if isinstance(v, SliceVal):
                return False
            return True
        return isinstance(e, IndexAccess)

    def addr(self, e: Expr) -> ir.Value:
        """Address of expression; written to temporary alloca if not a place."""
        target = getattr(e, "box_fn", None)
        if target:  # converted to `Fn`: a new value
            tmp = self.alloca(self.llty(target))
            self.b.store(self.expr(e), tmp)
            return tmp
        if self.is_place(e) and self.soa_of(e) is None and not (
                isinstance(e, FieldAccess) and e.field_name == "len" and is_array_type(e.obj.ty or "")):
            return self.place(e)
        tmp = self.alloca(self.llty(e.ty))
        self.store_expr(e, tmp)
        return tmp

    def _field_slot(self, e: FieldAccess) -> ir.Value:
        """Address of a struct field, including a reference field's pointer slot (not the pointee)."""
        info = self.program.struct_infos[e.obj.ty or ""]
        if getattr(info.decl, "is_union", False):
            return self.b.bitcast(self.addr(e.obj), self.llty(info.fields[e.field_name]).as_pointer())
        idx = list(info.fields).index(e.field_name)
        return self.b.gep(self.addr(e.obj), [ir.Constant(I32, 0), ir.Constant(I32, idx)], inbounds=True)

    def place(self, e: Expr) -> ir.Value:
        b = self.b
        if isinstance(e, BorrowExpr):
            return self.addr(e.expr)
        if isinstance(e, (Call, MethodCall)) and getattr(e, "view_ptr", False):
            return self.call(e) if isinstance(e, Call) else self.method_call(e)
        if isinstance(e, BlockExpr) and getattr(e, "view_ptr", False):
            slot = self.alloca(self.llty(e.ty).as_pointer())
            self.yields.append(slot)
            prev = self.yield_ptr
            self.yield_ptr = True
            self.stmt(e.stmt)
            self.yield_ptr = prev
            self.yields.pop()
            return b.load(slot)
        if isinstance(e, Name):
            if e.name in self.vars:
                v = self.vars[e.name]
                if isinstance(v, SoaVar):
                    raise CodegenError(f"`{e.name}` is an `soa` array; can only be used as "
                                       f"`{e.name}[i].field` and `{e.name}[i]`.")
                if isinstance(v, SliceVal):
                    raise CodegenError(f"`{e.name}` is a slice value and does not have a memory address")
                if e.name in self.ref_locals:
                    return b.load(v)
                return v
            ckey = getattr(e, "const_key", None) or e.name
            if ckey in self.consts:
                return self.consts[ckey]
            raise CodegenError(f"unknown variable '{e.name}'")
        if isinstance(e, FieldAccess):
            oty = e.obj.ty or ""
            sv = self.soa_of(e.obj)
            if sv is not None:
                idx = self.soa_index(sv, e.obj)  # type: ignore[arg-type]
                return b.gep(sv.fields[e.field_name], [ir.Constant(I32, 0), idx], inbounds=True)
            if heap_kind(oty) == "Box" and e.field_name == "value":
                return b.extract_value(self.base_val(e.obj), 0)
            if heap_kind(oty) in ("Shared", "Arc") and e.field_name == "value":
                return b.gep(b.extract_value(self.base_val(e.obj), 0), [ir.Constant(I32, 0), ir.Constant(I32, 1)],
                             inbounds=True)
            if e.field_name == "len" and (oty == "str" or is_slice_type(oty) or heap_kind(oty) == "List"):
                return b.gep(self.base_addr(e.obj), [ir.Constant(I32, 0), ir.Constant(I32, 1)], inbounds=True)
            info = self.program.struct_infos.get(oty)
            if info is None:
                raise CodegenError(f"field access not supported on type '{oty}'")
            if getattr(info.decl, "is_union", False):  # every field starts at the union's first byte
                return b.bitcast(self.base_addr(e.obj), self.llty(info.fields[e.field_name]).as_pointer())
            idx = list(info.fields).index(e.field_name)
            p = b.gep(self.base_addr(e.obj), [ir.Constant(I32, 0), ir.Constant(I32, idx)], inbounds=True)
            return b.load(p) if e.field_name in info.field_modes else p
        if isinstance(e, IndexAccess):
            return self.index_ptr(e)
        raise CodegenError(f"adreslenemeyen ifade: {type(e).__name__}")

    def to_i64(self, v: ir.Value, ty: str | None) -> ir.Value:
        base = bounded_int_info(ty)[0] if (ty and is_bounded_int(ty)) else ty
        w = v.type.width  # type: ignore[attr-defined]
        if w == 64:
            return v
        if w < 64:
            return self.b.sext(v, I64) if base in SIGNED else self.b.zext(v, I64)
        return self.b.trunc(v, I64)

    def fail_if(self, bad: ir.Value, emit: Callable[[], None]) -> None:
        fail, ok = self.new_block("fail"), self.new_block("ok")
        br = self.b.cbranch(bad, fail, ok)
        br.set_metadata("prof", self.prof_cold_meta())
        self.at(fail)
        emit()
        self.b.unreachable()
        self.at(ok)

    def panic_call(self, msg: str, line: int, col: int) -> None:
        call = self.b.call(self.rt_panic(), [self.cstr(msg), self.cstr(self.filename), ir.Constant(I32, line),
                                             ir.Constant(I32, col)])
        call.attributes.add("noreturn")

    def index_ptr(self, e: IndexAccess) -> ir.Value:
        b = self.b
        oty = e.obj.ty or ""
        idx = self.to_i64(self.expr(e.index), e.index.ty)
        if is_ptr_type(oty):  # raw pointer: no bounds check (unsafe)
            return b.gep(self.expr(e.obj), [idx])
        if is_array_type(oty):
            n, _ = array_info(oty)
            base = self.base_addr(e.obj)
            if not self.unchecked and not self._is_check_eliminated(e):
                self._bounds(idx, ir.Constant(I64, n), e)
            return b.gep(base, [ir.Constant(I32, 0), idx], inbounds=True)
        # slice / string / List: { ptr, len, ... }
        if is_slice_type(oty) and isinstance(e.obj, Name) and e.obj.name in self.vars:
            sv = self.vars[e.obj.name]
            if isinstance(sv, SliceVal):
                if not self.unchecked and not self._is_check_eliminated(e):
                    self._bounds(idx, sv.len, e)
                return b.gep(sv.ptr, [idx], inbounds=True)
        val = self.base_val(e.obj)
        ptr, ln = b.extract_value(val, 0), b.extract_value(val, 1)
        if not self.unchecked and not self._is_check_eliminated(e):
            self._bounds(idx, ln, e)
        return b.gep(ptr, [idx], inbounds=True)

    def _bounds(self, idx: ir.Value, ln: ir.Value, e: Expr) -> None:
        bad = self.b.icmp_unsigned(">=", idx, ln)
        def _emit_panic():
            call = self.b.call(self.rt_panic_bounds(), [
                idx, ln, self.cstr(self.filename), ir.Constant(I32, e.line), ir.Constant(I32, e.col)])
            call.attributes.add("noreturn")
        self.fail_if(bad, _emit_panic)

    # -- ifadeler -----------------------------------------------------------
    def store_expr(self, e: Expr, ptr: ir.Value) -> None:
        """Writes expression directly to `ptr` (avoids SSA copy for large aggregates)."""
        b = self.b
        if getattr(e, "box_fn", None):
            b.store(self.expr(e), ptr)
            return
        if isinstance(e, ArrayRepeatLit) and not isinstance(e.value, (IntLit, FloatLit, BoolLit)):
            n, elem = array_info(e.ty or "")
            v = self.expr(e.value)
            self.loop_n(ir.Constant(I64, n), lambda i: b.store(v, b.gep(ptr, [ir.Constant(I32, 0), i], inbounds=True)))
        elif isinstance(e, ArrayRepeatLit):
            n, elem = array_info(e.ty or "")
            v = self.expr(e.value)
            if isinstance(v, ir.Constant) and v.constant in (0, 0.0, False):
                b.store(ir.Constant(self.llty(e.ty), None), ptr)
            else:
                self.loop_n(ir.Constant(I64, n), lambda i: b.store(v, b.gep(ptr, [ir.Constant(I32, 0), i], inbounds=True)))
        elif isinstance(e, ArrayLit):
            b.store(ir.Constant(self.llty(e.ty), None), ptr)
            for i, el in enumerate(e.elements):
                b.store(self.expr(el), b.gep(ptr, [ir.Constant(I32, 0), ir.Constant(I32, i)], inbounds=True))
        elif isinstance(e, StructLit):
            info = self.program.struct_infos[e.ty or e.type_name]
            b.store(ir.Constant(self.llty(e.ty), None), ptr)
            order = list(info.fields)
            if getattr(info.decl, "is_union", False):
                for f in e.fields:
                    v = self.expr(f.value)
                    b.store(v, b.bitcast(ptr, v.type.as_pointer()))
                return
            for f in e.fields:
                v = self.addr(f.value) if f.ref_mode else self.expr(f.value)
                b.store(v, b.gep(ptr, [ir.Constant(I32, 0), ir.Constant(I32, order.index(f.name))], inbounds=True))
        elif isinstance(e, (Call, MethodCall)) and e.ctor_enum is not None:
            self.variant_into(ptr, e.ctor_enum, e.callee if isinstance(e, Call) else e.method, e.args)
        elif isinstance(e, (Name, FieldAccess)) and e.ctor_enum is not None:
            self.variant_into(ptr, e.ctor_enum, e.name if isinstance(e, Name) else e.field_name, [])
        else:
            val = self.expr(e)
            target_ty = ptr.type.pointee
            if isinstance(val.type, ir.IntType) and isinstance(target_ty, ir.IntType) and val.type != target_ty:
                val = self.cast(val, f"i{val.type.width}", f"i{target_ty.width}")
            b.store(val, ptr)

    def variant_into(self, ptr: ir.Value, ety: str, variant: str, args: list[Expr]) -> None:
        info = self.program.enum_infos[ety]
        vals = [self.expr(a) for a in args]
        self.b.store(ir.Constant(I32, self.tag_index(info, variant)),
                     self.b.gep(ptr, [ir.Constant(I32, 0), ir.Constant(I32, 0)], inbounds=True))
        for i, v in enumerate(vals):
            self.b.store(v, self.payload_ptr(ptr, ety, variant, i))

    def aggregate(self, e: Expr) -> ir.Value:
        tmp = self.alloca(self.llty(e.ty))
        self.store_expr(e, tmp)
        return self.b.load(tmp)

    def moved(self, e: Name) -> ir.Value:
        flag = self.flags.get(e.name)
        if flag is not None and self.nd(e.ty):
            self.b.store(ir.Constant(I1, 0), flag)
        return self.b.load(self.place(e))

    def cast(self, v: ir.Value, src: str, dst: str) -> ir.Value:
        b = self.b
        src = bounded_int_info(src)[0] if is_bounded_int(src) else src
        dst = bounded_int_info(dst)[0] if is_bounded_int(dst) else dst
        if src == dst:
            return v
        if dst in FLOATS:
            if src in FLOATS:
                return b.fpext(v, F64) if dst == "f64" else b.fptrunc(v, F32)
            return b.sitofp(v, self.llty(dst)) if src in SIGNED else b.uitofp(v, self.llty(dst))
        if dst == "bool":
            if src in FLOATS:
                return b.fcmp_unordered("!=", v, ir.Constant(v.type, 0.0))
            return b.icmp_unsigned("!=", v, ir.Constant(v.type, 0))
        dl = self.llty(dst)
        if src in FLOATS:
            return b.fptosi(v, dl) if dst in SIGNED else b.fptoui(v, dl)
        sw, dw = v.type.width, dl.width  # type: ignore[attr-defined]
        if dw > sw:
            return b.sext(v, dl) if src in SIGNED else b.zext(v, dl)
        if dw < sw:
            return b.trunc(v, dl)
        return v

    def arith(self, op: str, ty: str, l: ir.Value, r: ir.Value, line: int, col: int, rty: str | None = None) -> ir.Value:
        b = self.b
        if ty in simd.SIMD_TYPES:
            return simd.arith(self, op, ty, l, r)
        ty = bounded_int_info(ty)[0] if is_bounded_int(ty) else ty
        if ty in FLOATS:
            return {"+": b.fadd, "-": b.fsub, "*": b.fmul, "/": b.fdiv, "%": b.frem}[op](l, r)
        if ty == "bool":
            return {"&": b.and_, "|": b.or_, "^": b.xor}[op](l, r)
        signed = ty in SIGNED
        if op in ("wrapping_add", "wrapping_sub", "wrapping_mul") or (op in ("+", "-", "*") and self.is_wrapping()):
            if op in ("+", "wrapping_add"): return b.add(l, r)
            if op in ("-", "wrapping_sub"): return b.sub(l, r)
            if op in ("*", "wrapping_mul"): return b.mul(l, r)
        if op in ("saturating_add", "saturating_sub"):
            w = BITS.get(ty, 64)
            sat_op = "add" if op == "saturating_add" else "sub"
            prefix = "s" if signed else "u"
            iname = f"llvm.{prefix}{sat_op}.sat.i{w}"
            fn = self.mod.globals.get(iname)
            if fn is None:
                it = ir.IntType(w)
                fn = ir.Function(self.mod, ir.FunctionType(it, [it, it]), iname)
            return b.call(fn, [l, r])
        if op in ("+", "-", "*") and ty in INTS:
            w = BITS.get(ty, 64)
            op_name = {"+": "add", "-": "sub", "*": "mul"}[op]
            prefix = "s" if signed else "u"
            iname = f"llvm.{prefix}{op_name}.with.overflow.i{w}"
            fn = self.mod.globals.get(iname)
            if fn is None:
                it = ir.IntType(w)
                fn = ir.Function(self.mod, ir.FunctionType(ir.LiteralStructType([it, I1]), [it, it]), iname)
            res_struct = b.call(fn, [l, r])
            res_val = b.extract_value(res_struct, 0)
            ovf_bit = b.extract_value(res_struct, 1)
            self.fail_if(ovf_bit, lambda: self.panic_call("integer overflow", line, col))
            return res_val
        if op == "&": return b.and_(l, r)
        if op == "|": return b.or_(l, r)
        if op == "^": return b.xor(l, r)
        if op in ("/", "%"):
            zero = ir.Constant(l.type, 0)
            self.fail_if(b.icmp_unsigned("==", r, zero), lambda: self.panic_call("division by zero", line, col))
            if signed:
                lo = ir.Constant(l.type, -(1 << (BITS[ty] - 1)) if BITS[ty] > 1 else 0)
                bad = b.and_(b.icmp_signed("==", l, lo), b.icmp_signed("==", r, ir.Constant(l.type, -1)))
                self.fail_if(bad, lambda: self.panic_call("integer division overflow", line, col))
                return b.sdiv(l, r) if op == "/" else b.srem(l, r)
            return b.udiv(l, r) if op == "/" else b.urem(l, r)
        if op in ("<<", ">>"):
            width = BITS[ty]
            self.fail_if(b.icmp_unsigned(">=", r, ir.Constant(r.type, width)),
                         lambda: self.panic_call("shift amount out of bounds", line, col))
            rw, lw = r.type.width, l.type.width  # type: ignore[attr-defined]
            amt = b.zext(r, l.type) if rw < lw else b.trunc(r, l.type) if rw > lw else r
            if op == "<<":
                return b.shl(l, amt)
            return b.ashr(l, amt) if signed else b.lshr(l, amt)
        raise CodegenError(f"unsupported operator '{op}'")

    def compare(self, op: str, ty: str, l: ir.Value, r: ir.Value) -> ir.Value:
        b = self.b
        ty = bounded_int_info(ty)[0] if is_bounded_int(ty) else ty
        if ty == "str":
            eq = b.call(self.rt_str_eq(), [l, r])
            return eq if op == "==" else b.not_(eq)
        if ty in FLOATS:
            return b.fcmp_unordered("!=", l, r) if op == "!=" else b.fcmp_ordered(op, l, r)
        if ty in SIGNED:
            return b.icmp_signed(op, l, r)
        return b.icmp_unsigned(op, l, r)

    def expr(self, e: Expr) -> ir.Value:
        target = getattr(e, "box_fn", None)
        if not target:
            return self._expr_value(e)
        e.box_fn = None  # type: ignore[attr-defined]  # the plain value first, then wrap it
        try:
            v = self._expr_value(e)
        finally:
            e.box_fn = target  # type: ignore[attr-defined]
        return self.box_value(v, e.ty or "", target)

    def _expr_value(self, e: Expr) -> ir.Value:
        b = self.b
        if isinstance(e, IntLit):
            ty = bounded_int_info(e.ty)[0] if (e.ty and is_bounded_int(e.ty)) else (e.ty or "i32")
            if ty in FLOATS:
                return ir.Constant(self.llty(ty), float(e.value))
            return ir.Constant(self.llty(ty), _wrap_const(e.value, BITS.get(ty, 32)))
        if isinstance(e, FloatLit):
            return ir.Constant(self.llty(e.ty or "f64"), float(e.text))
        if isinstance(e, CharLit):
            return ir.Constant(I8, _wrap_const(e.value, 8))
        if isinstance(e, StrLit):
            return self.str_const(e.value)
        if isinstance(e, BoolLit):
            return ir.Constant(I1, 1 if e.value else 0)
        if isinstance(e, Name):
            if getattr(e, "func_ref", False):  # function used as a value (function pointer)
                return self.funcs[func_cname(getattr(e, "func_key", e.name))]
            if getattr(e, "is_null", False):
                return ir.Constant(self.llty(e.ty), None)
            if e.ctor_enum is not None:
                return self.aggregate_variant(e.ctor_enum, e.name, [], e)
            if getattr(e, "is_move", False):
                return self.moved(e)
            v = self.vars.get(e.name)
            if isinstance(v, SliceVal):
                return v.get_struct(b, self.llty(e.ty))
            ld = b.load(self.place(e))
            if getattr(e, "ty", None) and is_bounded_int(e.ty):
                base, lo, hi = bounded_int_info(e.ty)
                ld.set_metadata("range", self.range_meta(self.llty(base), lo, hi))
            return ld
        if isinstance(e, CopyExpr):
            return self.expr(e.expr)
        if isinstance(e, SoaExpr):
            return ir.Constant(self.llty(e.ty), None)
        if isinstance(e, FieldAccess):
            ckey = getattr(e, "const_key", None)
            if ckey and ckey in self.consts:
                return b.load(self.consts[ckey])
            if e.ctor_enum is not None:
                return self.aggregate_variant(e.ctor_enum, e.field_name, [], e)
            oty = e.obj.ty or ""
            if e.field_name == "len" and is_array_type(oty):
                return ir.Constant(I64, array_info(oty)[0])
            if e.field_name == "len" and is_slice_type(oty):
                if isinstance(e.obj, Name) and e.obj.name in self.vars:
                    v = self.vars[e.obj.name]
                    if isinstance(v, SliceVal):
                        return v.len
                len_ptr = b.gep(self.addr(e.obj), [ir.Constant(I32, 0), ir.Constant(I32, 1)], inbounds=True)
                ld = b.load(len_ptr)
                ld.set_metadata("range", self.range_meta_i64_pos())
                return ld
            if e.field_name == "len" and (oty == "str" or heap_kind(oty) == "List"):
                len_ptr = b.gep(self.base_addr(e.obj), [ir.Constant(I32, 0), ir.Constant(I32, 1)], inbounds=True)
                ld = b.load(len_ptr)
                ld.set_metadata("range", self.range_meta_i64_pos())
                return ld
            ld = b.load(self.place(e))
            if getattr(e, "ty", None) and is_bounded_int(e.ty):
                base, lo, hi = bounded_int_info(e.ty)
                ld.set_metadata("range", self.range_meta(self.llty(base), lo, hi))
            return ld
        if isinstance(e, IndexAccess):
            sv = self.soa_of(e)
            if sv is not None:
                return self.soa_gather(sv, e)
            ld = b.load(self.index_ptr(e))
            if getattr(e, "ty", None) and is_bounded_int(e.ty):
                base, lo, hi = bounded_int_info(e.ty)
                ld.set_metadata("range", self.range_meta(self.llty(base), lo, hi))
            return ld
        if isinstance(e, (ArrayLit, ArrayRepeatLit, StructLit)):
            return self.aggregate(e)
        if isinstance(e, SliceExpr):
            return self.slice_expr(e)
        if isinstance(e, Cast):
            return self.cast(self.expr(e.expr), e.expr.ty or "i32", e.target_type)
        if isinstance(e, (Unary, Binary)) and getattr(e, "overload", None) is not None:
            return self.expr(e.overload)  # operator overloading: resolved to a method call
        if isinstance(e, Unary):
            v = self.expr(e.operand)
            if e.op == "not" or e.op == "~":
                return b.not_(v)
            if e.ty in FLOATS:
                return b.fsub(ir.Constant(v.type, -0.0), v)
            return b.neg(v)
        if isinstance(e, Binary):
            return self.binary(e)
        if isinstance(e, FormatStr):
            return self.format_str(e)
        if isinstance(e, BorrowExpr):
            return b.load(self.place(e))
        if isinstance(e, BlockExpr):
            if getattr(e, "view_ptr", False):
                return b.load(self.place(e))
            slot = self.alloca(self.llty(e.ty))
            self.yields.append(slot)
            self.stmt(e.stmt)
            self.yields.pop()
            return b.load(slot)
        if isinstance(e, Call):
            v = self.call(e)
            return b.load(v) if getattr(e, "view_ptr", False) else v
        if isinstance(e, MethodCall):
            v = self.method_call(e)
            return b.load(v) if getattr(e, "view_ptr", False) else v
        if isinstance(e, Apply):
            return self.with_temps(e, lambda: self.indirect_call(e, e.args))
        if isinstance(e, Try):
            return self.try_expr(e)
        raise CodegenError(f"beklenmeyen ifade: {type(e).__name__}")

    def aggregate_variant(self, ety: str, variant: str, args: list[Expr], e: Expr) -> ir.Value:
        tmp = self.alloca(self.llty(ety))
        self.variant_into(tmp, ety, variant, args)
        return self.b.load(tmp)

    def binary(self, e: Binary) -> ir.Value:
        b = self.b
        if e.op in ("and", "or"):
            l = self.expr(e.left)
            lblk = b.block
            rhs, end = self.new_block("rhs"), self.new_block("sc")
            if e.op == "and":
                b.cbranch(l, rhs, end)
            else:
                b.cbranch(l, end, rhs)
            self.at(rhs)
            r = self.expr(e.right)
            rblk = b.block
            b.branch(end)
            self.at(end)
            phi = b.phi(I1)
            phi.add_incoming(ir.Constant(I1, 0 if e.op == "and" else 1), lblk)
            phi.add_incoming(r, rblk)
            return phi
        if e.op == "+" and getattr(e, "ty", None) == "string":
            return self.format_str(FormatStr([e.left, e.right]))
        if getattr(e, "structural_eq", None):  # `a == b` on structs, enums, lists: field by field
            eq = self.eq_values(self.base_val(e.left), self.base_val(e.right), e.structural_eq)
            return eq if e.op == "==" else b.not_(eq)
        text = getattr(e, "text_order", None)
        if text:  # `a < b` on text: compare the bytes, then the lengths
            l, r = self.base_val(e.left), self.base_val(e.right)
            if text == "string":
                l, r = self._string_view(l), self._string_view(r)
            return b.icmp_signed(e.op, b.call(self.rt_str_cmp(), [l, r]), ir.Constant(I32, 0))
        l, r = self.expr(e.left), self.expr(e.right)
        if e.op in COMPARE:
            return self.compare(e.op, e.left.ty or "i32", l, r)
        return self.arith(e.op, e.ty or e.left.ty or "i32", l, r, e.line, e.col, e.right.ty)

    def zero_byte(self) -> ir.Value:
        g = self.mod.globals.get("gg_zero_byte")
        if g is None:
            g = ir.GlobalVariable(self.mod, I8, "gg_zero_byte")
            g.linkage = "internal"
            g.global_constant = True
            g.initializer = ir.Constant(I8, 0)
        return g

    def slice_expr(self, e: SliceExpr) -> ir.Value:
        b = self.b
        oty = e.obj.ty or ""
        if is_array_type(oty):
            n, _ = array_info(oty)
            ptr = b.gep(self.addr(e.obj), [ir.Constant(I32, 0), ir.Constant(I32, 0)], inbounds=True)
            ln: ir.Value = ir.Constant(I64, n)
        else:
            v = self.expr(e.obj)
            ptr, ln = b.extract_value(v, 0), b.extract_value(v, 1)
        lo = self.to_i64(self.expr(e.start), e.start.ty) if e.start is not None else ir.Constant(I64, 0)
        if e.end is None:
            hi = ln
        else:
            hi = self.to_i64(self.expr(e.end), e.end.ty)
            if e.inclusive:
                hi = b.add(hi, ir.Constant(I64, 1))
        if not self.unchecked:
            bad = b.or_(b.icmp_signed("<", lo, ir.Constant(I64, 0)),
                        b.or_(b.icmp_signed("<", hi, lo), b.icmp_unsigned(">", hi, ln)))
            def _emit_slice_panic():
                call = b.call(self.rt_panic_slice(), [
                    lo, hi, ln, self.cstr(self.filename), ir.Constant(I32, e.line), ir.Constant(I32, e.col)])
                call.attributes.add("noreturn")
            self.fail_if(bad, _emit_slice_panic)
            if e.ty == "str":  # a bound inside a multi-byte character would cut it in half
                def mid_char(at: ir.Value) -> ir.Value:
                    inside = b.icmp_unsigned("<", at, ln)
                    # At or past the end there is no byte to look at (and an empty `string` has no buffer at
                    # all), so read a constant zero there instead.
                    where = b.select(inside, b.gep(ptr, [b.select(inside, at, ir.Constant(I64, 0))]), self.zero_byte())
                    byte = b.load(where)
                    cont = b.icmp_unsigned("==", b.and_(byte, ir.Constant(I8, 0xC0)), ir.Constant(I8, 0x80))
                    return b.and_(inside, cont)
                self.fail_if(b.or_(mid_char(lo), mid_char(hi)), lambda: self.panic_call(
                    "string slice bound is inside a UTF-8 character", e.line, e.col))
        res = ir.Constant(self.llty(e.ty), ir.Undefined)
        res = b.insert_value(res, b.gep(ptr, [lo], inbounds=True), 0)
        return b.insert_value(res, b.sub(hi, lo), 1)

    def borrow_arg(self, a: Expr) -> ir.Value:
        """Address of an argument lent as `read`/`lend`. A fresh owned value (`f(make_list())`) lives in a
        temporary that is freed right after the call (see `with_temps`)."""
        ptr = self.addr(a)
        ty = getattr(a, "box_fn", None) or a.ty
        if self.temp_drops is not None and (not self.is_place(a) or getattr(a, "box_fn", None)) and self.nd(ty):
            self.temp_drops.append((ptr, ty or "", a))
        return ptr

    def fresh_owned(self, e: Expr) -> bool:
        """Is `e` a fresh owned value (a call, a constructor) that the surrounding expression only looks into?"""
        return not self.is_place(e) and not getattr(e, "box_fn", None) and self.nd(e.ty)

    def base_addr(self, e: Expr) -> ir.Value:
        """Address of `e` as the base of a field, element, `.len`, or built-in method. A fresh owned base
        (`make().text`, `nums()[0]`) lives in a temporary that is freed like an argument temporary."""
        ptr = self.addr(e)
        if self.fresh_owned(e) and not self.terminated():
            if self.temp_drops is not None:
                self.temp_drops.append((ptr, e.ty or "", e))
            else:
                self.keep_temp(ptr, e.ty or "")
        return ptr

    def base_val(self, e: Expr) -> ir.Value:
        """`base_addr`, loaded."""
        if not self.fresh_owned(e):
            return self.expr(e)
        return self.b.load(self.base_addr(e))

    def with_temps(self, e: Expr, emit: Callable[[], ir.Value]) -> ir.Value:
        """Runs `emit` (argument evaluation + call), then frees owned temporaries lent to that call.
        A call returning a view (`-> ref T`) may point into them, so those are kept."""
        saved = self.temp_drops
        self.temp_drops = []
        try:
            result = emit()
        finally:
            temps, self.temp_drops = self.temp_drops, saved
        if not temps or self.terminated():
            return result
        if getattr(e, "view_ptr", False):  # `-> ref T`: only the argument it is tied to must stay alive
            tie = getattr(e, "tie_expr", None)
            direct = list(getattr(e, "args", []) or []) + ([e.obj] if isinstance(e, MethodCall) else [])
            keep = (lambda a: True) if tie is None else (
                lambda a: a is tie or not any(a is d for d in direct))
        elif self.may_borrow(e.ty):
            keep = lambda a: True  # noqa: E731
        else:
            keep = lambda a: False  # noqa: E731
        for ptr, ty, arg in temps:
            if keep(arg):
                self.keep_temp(ptr, ty)
            else:
                self.b.call(self.drop_fn(ty), [self.b.load(ptr)])
        return result

    def keep_temp(self, ptr: ir.Value, ty: str) -> None:
        """Keeps a temporary that a call result may point into. When the statement only uses the result
        right away (an expression statement, `n += f(make())`), it lives to the end of the enclosing block.
        When the statement stores something that may still point into it, it lives to the end of the
        function; for `return` it is not freed at all (view lifetimes are not tracked yet)."""
        s = self.cur_stmt
        if isinstance(s, Return):
            if s.value is not None and self.may_borrow(s.value.ty):
                return
            scope = self.scopes[-1]
        elif isinstance(s, VarDecl) and self.may_borrow(s.ty or s.value.ty):
            scope = self.scopes[0]
        elif isinstance(s, Assign) and self.may_borrow(s.target.ty):
            scope = self.scopes[0]
        else:
            scope = self.scopes[-1]
        flag = self.alloca(I1, "live.tmp")
        self.entry_b.store(ir.Constant(I1, 0), flag)  # not created on every path
        self.b.store(ir.Constant(I1, 1), flag)
        scope.append(("@temp", ty, ptr, flag))

    def may_borrow(self, ty: str | None, seen: frozenset[str] = frozenset()) -> bool:
        """Can a value of `ty` point into another value (`str`, slice, pointer, reference field)?"""
        if not ty or ty in seen or ty in BITS or ty in ("bool", "f32", "f64", "void"):
            return False
        if ty == "str" or is_slice_type(ty) or is_ptr_type(ty) or is_fn_type(ty):
            return True
        seen = seen | {ty}
        if is_array_type(ty):
            return self.may_borrow(array_info(ty)[1], seen)
        if heap_kind(ty) is not None:
            return self.may_borrow(heap_inner(ty), seen)
        info = self.program.struct_infos.get(ty)
        if info is not None:
            return bool(info.field_modes) or any(self.may_borrow(t, seen) for t in info.fields.values())
        einfo = self.program.enum_infos.get(ty)
        if einfo is not None:
            return any(self.may_borrow(t, seen) for v in einfo.variants.values() for t in v.payload)
        return False

    def call_arg(self, a: Expr, param_ty: str | None, is_extern: bool = False, mode: str = "") -> ir.Value:
        b = self.b
        if is_extern and param_ty == "str":
            if isinstance(a, StrLit):
                return self.cstr(a.value)
            return b.extract_value(self.expr(a), 0)
        if param_ty is not None and is_slice_type(param_ty):
            if is_array_type(a.ty or ""):
                n, _ = array_info(a.ty or "")
                # a fresh array (`f(["a", "b"])`) lives in a temporary freed after the call
                ptr = b.gep(self.base_addr(a), [ir.Constant(I32, 0), ir.Constant(I32, 0)], inbounds=True)
                res = ir.Constant(self.llty(param_ty), ir.Undefined)
                res = b.insert_value(res, ptr, 0)
                return b.insert_value(res, ir.Constant(I64, n), 1)
            if heap_kind(a.ty or "") == "List":
                lv = self.base_val(a)  # a fresh list (`f(make())`) is freed after the call
                ptr = b.extract_value(lv, 0)
                ln = b.extract_value(lv, 1)
                res = ir.Constant(self.llty(param_ty), ir.Undefined)
                res = b.insert_value(res, ptr, 0)
                return b.insert_value(res, ln, 1)
            return self.expr(a)  # a slice value (sub-slice or slice parameter) is passed as (ptr, len)
        if mode in ("lend", "read"):
            return self.borrow_arg(a)
        v = self.expr(a)
        if param_ty is not None:
            target_llty = self.llty(param_ty)
            if isinstance(v.type, ir.IntType) and isinstance(target_llty, ir.IntType) and v.type != target_llty:
                v = self.cast(v, f"i{v.type.width}", f"i{target_llty.width}")
        return v

    def indirect_call(self, e: Expr, args_e: list[Expr]) -> ir.Value:
        """Call through a function value (`f(x)` with `f: fn(..) -> ..` or `f: Fn(..) -> ..`, or `s.cb(x)`)."""
        callee = e.callee_expr  # type: ignore[attr-defined]
        fty = callee.ty or ""
        ptys = getattr(e, "param_tys", [])
        if is_boxed_fn(fty):
            box = self.expr(callee)
            code = self.b.bitcast(self.b.extract_value(box, 0), self.thunk_type(fty).as_pointer())
            args = [self.call_arg(a, ptys[i] if i < len(ptys) else None) for i, a in enumerate(args_e)]
            result = self.b.call(code, [self.b.extract_value(box, 1)] + args)
            if self.is_temp(callee) and not self.may_borrow(getattr(e, "ty", None)):
                self.b.call(self.drop_fn(fty), [box])  # `make_adder(5)(1)`: the temporary closure is done
            return result
        fn = self.expr(callee)
        args = [self.call_arg(a, ptys[i] if i < len(ptys) else None) for i, a in enumerate(args_e)]
        return self.b.call(fn, args)

    # -- owned closures (`Fn(A) -> R`) ------------------------------------------------------------
    # A `Fn` value is { code, env }. `code` takes the environment first: R code(i8* env, A...).
    # `env` points to { i64 count, void(i8*)* dropper, payload } on the heap (null never happens).
    @staticmethod
    def env_header() -> ir.Type:
        return ir.LiteralStructType([I64, ir.FunctionType(VOID, [I8P]).as_pointer()])

    def thunk_type(self, fty: str) -> ir.FunctionType:
        params, ret = fn_parts(fty)
        return ir.FunctionType(self.llty(ret), [I8P] + [self.llty(t) for t in params])

    def box_value(self, v: ir.Value, src: str, dst: str) -> ir.Value:
        """Wraps a function pointer or a closure value into an owned `Fn` value, or a value into a `dyn F`."""
        b = self.b
        if is_dyn_type(dst):
            data = b.call(self.rt_alloc(), [self.sizeof(v.type)])
            b.store(v, b.bitcast(data, v.type.as_pointer()))
            out = b.insert_value(ir.Constant(self.llty(dst), ir.Undefined), data, 0)
            return b.insert_value(out, self.dyn_table(src, dyn_feature(dst)), 1)
        payload_ty = v.type
        env_ty = ir.LiteralStructType([I64, self.env_header().elements[1], payload_ty])
        env = b.bitcast(b.call(self.rt_alloc(), [self.sizeof(env_ty)]), env_ty.as_pointer())
        field = lambda k: b.gep(env, [ir.Constant(I32, 0), ir.Constant(I32, k)], inbounds=True)  # noqa: E731
        b.store(ir.Constant(I64, 1), field(0))
        if is_fn_type(src):
            b.store(ir.Constant(self.env_header().elements[1], None), field(1))
            code = self.fnptr_thunk(dst, payload_ty)
        else:
            b.store(self.env_dropper(src, env_ty), field(1))
            code = self.closure_thunk(src, dst, env_ty)
        b.store(v, field(2))
        out = b.insert_value(ir.Constant(self.llty(dst), ir.Undefined), b.bitcast(code, I8P), 0)
        return b.insert_value(out, b.bitcast(env, I8P), 1)

    # -- `dyn F`: tables and calls -----------------------------------------------------------------
    def dyn_methods(self, fkey: str) -> list:
        feat = next(d for d in self.program.decls if type(d).__name__ == "FeatureDecl"
                    and (d.name == fkey or fkey.endswith("::" + d.name)) and self._feature_key(d) == fkey)
        return feat.methods

    @staticmethod
    def _feature_key(d) -> str:
        slug = "" if getattr(d, "from_prelude", False) else (getattr(d, "module_slug", "") or "")
        return f"{slug}::{d.name}" if slug else d.name

    def dyn_table(self, ty: str, fkey: str) -> ir.Value:
        """`[drop, method 0, method 1, ...]` of `ty` as a `dyn fkey`, one global per pair."""
        name = f"gg_dyn_{self._ident(ty)}__{self._ident(fkey)}"
        g = self.mod.globals.get(name)
        if g is None:
            entries = [self.dyn_drop_thunk(ty)]
            for m in self.dyn_methods(fkey):
                if m.params and m.params[0].name == "self" and func_cname(f"{ty}.{m.name}") in self.funcs:
                    entries.append(self.dyn_method_thunk(ty, m.name))
                else:
                    entries.append(ir.Constant(I8P, None))
            arr = ir.ArrayType(I8P, len(entries))
            g = ir.GlobalVariable(self.mod, arr, name)
            g.linkage = "internal"
            g.global_constant = True
            g.initializer = ir.Constant(arr, [e if isinstance(e, ir.Constant) else e.bitcast(I8P) for e in entries])
        return self.b.gep(g, [ir.Constant(I32, 0), ir.Constant(I32, 0)], inbounds=True)

    def dyn_drop_thunk(self, ty: str) -> ir.Function:
        name = "gg_dyndrop_" + self._ident(ty)
        fn = self.mod.globals.get(name)
        if fn is not None:
            return fn
        fn = ir.Function(self.mod, ir.FunctionType(VOID, [I8P]), name)
        fn.linkage = "internal"
        with self.func_ctx(fn):
            b = self.b
            if self.nd(ty):
                b.call(self.drop_fn(ty), [b.load(b.bitcast(fn.args[0], self.llty(ty).as_pointer()))])
            b.call(self.rt_free(), [fn.args[0]])
            b.ret_void()
            self.finish_entry()
        return fn

    def dyn_method_thunk(self, ty: str, method: str) -> ir.Function:
        """`(data, args...) -> ret` that calls `ty.method` with `data` as its `self`."""
        target = self.funcs[func_cname(f"{ty}.{method}")]
        ftype = target.function_type
        name = f"gg_dynthunk_{self._ident(ty)}__{method}"
        fn = self.mod.globals.get(name)
        if fn is not None:
            return fn
        fn = ir.Function(self.mod, ir.FunctionType(ftype.return_type, [I8P] + list(ftype.args[1:])), name)
        fn.linkage = "internal"
        with self.func_ctx(fn):
            b = self.b
            self_ty = ftype.args[0]
            if isinstance(self_ty, ir.PointerType) and self_ty == self.llty(ty).as_pointer():
                first = b.bitcast(fn.args[0], self_ty)  # `self` by reference
            else:
                first = b.load(b.bitcast(fn.args[0], self.llty(ty).as_pointer()))  # a copy of `self`
            r = b.call(target, [first] + list(fn.args[1:]))
            b.ret_void() if ftype.return_type == VOID else b.ret(r)
            self.finish_entry()
        return fn

    def dyn_call(self, e: MethodCall) -> ir.Value:
        """`x.m(args)` on a `dyn F`: load entry `1 + index` of the table and call it with the value."""
        b = self.b
        fat = self.base_val(e.obj)
        data, table = b.extract_value(fat, 0), b.extract_value(fat, 1)
        ptys = getattr(e, "param_tys", [])
        modes = e.arg_modes
        args = [self.call_arg(a, ptys[i] if i < len(ptys) else None, mode=modes[i] if i < len(modes) else "")
                for i, a in enumerate(e.args)]
        ret = self.llty(e.ty) if e.ty and e.ty != "void" else VOID
        ftype = ir.FunctionType(ret, [I8P] + [a.type for a in args])
        slot = b.load(b.gep(table, [ir.Constant(I32, 1 + e.dyn_index)], inbounds=True))  # type: ignore[attr-defined]
        return b.call(b.bitcast(slot, ftype.as_pointer()), [data] + args)

    def fnptr_thunk(self, fty: str, ptr_ty: ir.Type) -> ir.Function:
        name = "gg_fnthunk_" + self._ident(fty)
        fn = self.mod.globals.get(name)
        if fn is not None:
            return fn
        fn = ir.Function(self.mod, self.thunk_type(fty), name)
        fn.linkage = "internal"
        with self.func_ctx(fn):
            b = self.b
            env_ty = ir.LiteralStructType([I64, self.env_header().elements[1], ptr_ty])
            env = b.bitcast(fn.args[0], env_ty.as_pointer())
            target = b.load(b.gep(env, [ir.Constant(I32, 0), ir.Constant(I32, 2)], inbounds=True))
            r = b.call(target, list(fn.args[1:]))
            b.ret_void() if fn.function_type.return_type == VOID else b.ret(r)
            self.finish_entry()
        return fn

    def closure_thunk(self, closure: str, fty: str, env_ty: ir.Type) -> ir.Function:
        name = "gg_closurethunk_" + self._ident(closure)
        fn = self.mod.globals.get(name)
        if fn is not None:
            return fn
        lam = closure[len("__closure_"):]
        target = self.funcs[lam] if lam in self.funcs else self.funcs[func_cname(lam)]  # `__lambda_1[i32]`: an instance
        fn = ir.Function(self.mod, self.thunk_type(fty), name)
        fn.linkage = "internal"
        with self.func_ctx(fn):
            b = self.b
            env = b.bitcast(fn.args[0], env_ty.as_pointer())
            payload = b.gep(env, [ir.Constant(I32, 0), ir.Constant(I32, 2)], inbounds=True)
            r = b.call(target, self.expand_args(lam, [payload] + list(fn.args[1:])))
            b.ret_void() if fn.function_type.return_type == VOID else b.ret(r)
            self.finish_entry()
        return fn

    def env_dropper(self, closure: str, env_ty: ir.Type) -> ir.Value:
        """Function freeing what a closure environment owns (null when it owns no heap memory)."""
        slot_ty = self.env_header().elements[1]
        if not self.nd(closure):
            return ir.Constant(slot_ty, None)
        name = "gg_envdrop_" + self._ident(closure)
        fn = self.mod.globals.get(name)
        if fn is None:
            fn = ir.Function(self.mod, ir.FunctionType(VOID, [I8P]), name)
            fn.linkage = "internal"
            with self.func_ctx(fn):
                b = self.b
                env = b.bitcast(fn.args[0], env_ty.as_pointer())
                payload = b.load(b.gep(env, [ir.Constant(I32, 0), ir.Constant(I32, 2)], inbounds=True))
                b.call(self.drop_fn(closure), [payload])
                b.ret_void()
                self.finish_entry()
        return fn

    def call(self, e: Call) -> ir.Value:
        b = self.b
        if getattr(e, "simd", None):
            return simd.call(self, e)
        if getattr(e, "builtin", None) in ("target_os", "target_arch"):
            return self.str_const(target_os(self.triple) if e.builtin == "target_os" else target_arch(self.triple))
        if getattr(e, "is_indirect", False):
            return self.indirect_call(e, e.args)
        builtin = getattr(e, "builtin", None)
        callee = getattr(e, "callee", "")
        if callee in ("to_json", "from_json") and getattr(e, "json_ty", None):
            return self.json_call(e)
        if callee == "hash" and getattr(e, "structural_hash", None):
            return self.hash_value(self.base_val(e.args[0]), e.structural_hash)
        if callee in ("print", "eprint") and e.ctor_enum is None:
            return self.print_call(e, err=(callee == "eprint"))
        if callee == "panic" and e.ctor_enum is None and e.args:
            if isinstance(e.args[0], StrLit):
                self.panic_call(e.args[0].value, e.line, e.col)
            else:  # the message is built at run time; the program stops, so it is never freed
                v = self.expr(e.args[0])
                if int_base(e.args[0].ty) == "string":
                    v = b.extract_value(v, 0)
                call = b.call(self.rt_panic_text(), [b.trunc(b.extract_value(v, 1), I32), b.extract_value(v, 0),
                                                     self.cstr(self.filename), ir.Constant(I32, e.line),
                                                     ir.Constant(I32, e.col)])
                call.attributes.add("noreturn")
            self.b.unreachable()
            self.start_dead()
            return ir.Constant(I32, 0)
        if isinstance(builtin, str) and builtin.startswith("ptr_") and e.ctor_enum is None:
            return self.ptr_builtin(e)
        if builtin == "vec_new":
            return ir.Constant(self.llty(e.ty), None)
        if builtin == "int_const":
            w = BITS[e.ty]
            v = e.const_value & ((1 << w) - 1)
            if v >= 1 << (w - 1):
                v -= 1 << w  # LLVM integer constants are written as signed values
            return ir.Constant(self.llty(e.ty), v)
        if isinstance(builtin, str) and builtin.startswith("ovf_"):
            x, y = self.expr(e.args[0]), self.expr(e.args[1])
            ty = e.args[0].ty
            w = BITS[ty]
            iname = f"llvm.{'s' if ty in SIGNED else 'u'}{builtin[4:]}.with.overflow.i{w}"
            fn = self.mod.globals.get(iname)
            if fn is None:
                it = ir.IntType(w)
                fn = ir.Function(self.mod, ir.FunctionType(ir.LiteralStructType([it, I1]), [it, it]), iname)
            return b.extract_value(b.call(fn, [x, y]), 1)
        if builtin == "shared_new":
            inner = heap_inner(e.ty or "")
            ct = ir.LiteralStructType([I64, self.llty(inner)])
            x = self.expr(e.args[0])
            p = b.bitcast(b.call(self.rt_alloc(), [self.sizeof(ct)]), ct.as_pointer())
            b.store(ir.Constant(I64, 1), b.gep(p, [ir.Constant(I32, 0), ir.Constant(I32, 0)], inbounds=True))
            b.store(x, b.gep(p, [ir.Constant(I32, 0), ir.Constant(I32, 1)], inbounds=True))
            return b.insert_value(ir.Constant(self.llty(e.ty), ir.Undefined), p, 0)
        if builtin == "box_new":
            inner = heap_inner(e.ty or "")
            it = self.llty(inner)
            x = self.expr(e.args[0])
            p = b.bitcast(b.call(self.rt_alloc(), [self.sizeof(it)]), it.as_pointer())
            b.store(x, p)
            return b.insert_value(ir.Constant(self.llty(e.ty), ir.Undefined), p, 0)
        if callee == "input":
            arg = self.expr(e.args[0]) if e.args else self.str_const("")
            return b.call(self.rt_input(), [arg])
        if getattr(e, "is_string_conv", False):
            arg = e.args[0]
            aty = getattr(arg, "ty", "")
            if aty == "str":
                return self.b.call(self.funcs["string_from"], [self.expr(arg)])
            if aty == "string":
                return self.expr(arg)
            return self.format_str(FormatStr([arg]))
        if e.ctor_enum is not None:
            return self.aggregate_variant(e.ctor_enum, callee, e.args, e)
        if getattr(e, "cast_to", None) is not None:
            return self.cast(self.expr(e.args[0]), e.args[0].ty or "i32", e.cast_to)
        return self.with_temps(e, lambda: self.direct_call(e, callee))

    def direct_call(self, e: Call, callee: str) -> ir.Value:
        b = self.b
        is_ext = getattr(e, "is_extern", False)
        param_tys = getattr(e, "param_tys", [])
        modes = e.arg_modes
        nfixed = len(param_tys)
        args = [self.call_arg(a, param_tys[i] if i < nfixed else None, is_extern=is_ext,
                              mode=modes[i] if i < len(modes) else "") for i, a in enumerate(e.args)]
        vtys = getattr(e, "vararg_tys", None)
        if vtys is not None:  # variadic: C default argument promotions
            for i in range(nfixed, len(args)):
                args[i] = self.promote_vararg(args[i], vtys[i - nfixed])
        raw = getattr(e, "func_key", None) or callee
        if is_ext or raw in self.externs or callee in self.externs:
            fn = self.externs[raw if raw in self.externs else callee]
            if fn.name in self.c_plans:
                return self.c_call(fn, args)
            if fn.name in self.wasi_declared:
                declared_ret, signed = self.wasi_declared[fn.name]
                return self._wasi_narrow_call(fn, args, declared_ret, signed)
        else:
            inst = getattr(e, "inst_key", None)
            key = func_cname(inst) if inst is not None else (func_cname(raw) if "::" in str(raw) else raw)
            fn = self.funcs[key]
            args = self.expand_args(key, args)
        return b.call(fn, args)

    def promote_vararg(self, v: ir.Value, ty: str) -> ir.Value:
        """C default argument promotion: f32 -> double, narrow int/bool -> int, string -> `char*`."""
        b = self.b
        if ty == "f32":
            return b.fpext(v, F64)
        if ty == "str":
            return b.extract_value(v, 0)
        if ty in BITS:
            w = BITS[ty]
            if w < 32:
                return b.sext(v, I32) if ty in SIGNED else b.zext(v, I32)
        return v

    def ptr_builtin(self, e: Call) -> ir.Value:
        """FFI pointer builtins (see TypeChecker._ptr_builtin)."""
        b = self.b
        bi = getattr(e, "builtin", "")
        name = bi[4:] if bi.startswith("ptr_") else e.callee
        if name in ("size_of", "align_of"):
            lt = self.llty(e.mem_ty)  # type: ignore[attr-defined]
            if name == "size_of":
                end = ir.Constant(lt.as_pointer(), None).gep([ir.Constant(I32, 1)])
            else:  # offset of T after one byte in `{i8, T}` is T's alignment
                pair = ir.LiteralStructType([I8, lt])
                end = ir.Constant(pair.as_pointer(), None).gep([ir.Constant(I32, 0), ir.Constant(I32, 1)])
            return end.ptrtoint(I64)
        if name.startswith("atomic_") or name == "fence":
            return self.atomic_builtin(e, name)
        if name == "asm":
            args = [self.expr(a) for a in e.args[2:]]
            ret = VOID if not e.ty or e.ty == "void" else self.llty(e.ty)
            ftype = ir.FunctionType(ret, [a.type for a in args])
            r = b.asm(ftype, e.args[0].value, e.args[1].value, args, True)  # type: ignore[attr-defined]
            return r if ret != VOID else ir.Constant(I32, 0)
        if name in ("volatile_read", "volatile_write"):
            p = b.bitcast(self.expr(e.args[0]), self.llty(e.mem_ty).as_pointer())  # type: ignore[attr-defined]
            if name == "volatile_read":
                instr = _VolatileLoad(b.block, p)
                b._insert(instr)
                return instr
            b._insert(_VolatileStore(b.block, self.expr(e.args[1]), p))
            return ir.Constant(I32, 0)
        if name == "ptr_write":
            p = b.bitcast(self.expr(e.args[0]), self.llty(e.mem_ty).as_pointer())  # type: ignore[attr-defined]
            modes = e.arg_modes
            b.store(self.call_arg(e.args[1], e.mem_ty, mode=modes[1] if len(modes) > 1 else ""), p)  # type: ignore[attr-defined]
            return ir.Constant(I32, 0)
        if name in ("addr", "addr_mut"):
            arg = e.args[0]
            kind = getattr(e, "addr_kind", "val")
            if kind == "val":
                p = self.addr(arg)
                want = self.llty(e.ty)
                return b.bitcast(p, want) if p.type != want else p  # an owner's bytes are a `*u8`
            if kind == "array":
                return b.gep(self.addr(arg), [ir.Constant(I32, 0), ir.Constant(I32, 0)], inbounds=True)
            return b.extract_value(self.expr(arg), 0)  # slice / string: data pointer
        v = self.expr(e.args[0])
        if name == "ptr_cast":
            return b.bitcast(v, self.llty(e.ty))
        if name == "ptr_to_int":
            return b.ptrtoint(v, I64)
        if name == "int_to_ptr":
            return b.inttoptr(v, self.llty(e.ty))
        if name == "ptr_offset":
            return b.gep(v, [self.to_i64(self.expr(e.args[1]), e.args[1].ty)])
        if name == "ptr_read":
            return b.load(b.bitcast(v, self.llty(e.mem_ty).as_pointer()))  # type: ignore[attr-defined]
        if name == "slice_from_raw":
            slice_ty = self.llty(e.ty)
            res = ir.Constant(slice_ty, ir.Undefined)
            res = b.insert_value(res, b.bitcast(v, slice_ty.elements[0]), 0)
            return b.insert_value(res, self.to_i64(self.expr(e.args[1]), e.args[1].ty), 1)
        if name == "str_from_raw":
            res = ir.Constant(self.llty("str"), ir.Undefined)
            res = b.insert_value(res, b.bitcast(v, I8P), 0)
            return b.insert_value(res, self.to_i64(self.expr(e.args[1]), e.args[1].ty), 1)
        if name == "string_to_cstr":
            return b.extract_value(v, 0)
        if name == "cstr_to_string":
            p = b.bitcast(v, I8P)
            n = b.call(self.c_fn("strlen", I64, [I8P]), [p])
            res = ir.Constant(self.llty("str"), ir.Undefined)
            return b.insert_value(b.insert_value(res, p, 0), n, 1)
        raise CodegenError(f"unknown pointer builtin '{name}'")

    def atomic_builtin(self, e: Call, name: str) -> ir.Value:
        b = self.b
        order = {"relaxed": "monotonic"}.get(e.atomic_order, e.atomic_order)  # type: ignore[attr-defined]
        if name == "fence":
            b.fence(order)
            return ir.Constant(I32, 0)
        lt = self.llty(e.mem_ty)  # type: ignore[attr-defined]
        size = lt.width // 8
        p = b.bitcast(self.expr(e.args[0]), lt.as_pointer())
        vals = [self.expr(a) for a in e.args[1:-1]]
        if name == "atomic_load":
            return b.load_atomic(p, order, size)
        if name == "atomic_store":
            b.store_atomic(vals[0], p, order, size)
            return ir.Constant(I32, 0)
        if name == "atomic_cas":
            fail = {"release": "monotonic", "acq_rel": "acquire"}.get(order, order)
            return b.extract_value(b.cmpxchg(p, vals[0], vals[1], order, fail), 0)
        op = {"atomic_add": "add", "atomic_sub": "sub", "atomic_and": "and", "atomic_or": "or",
              "atomic_xor": "xor", "atomic_swap": "xchg"}[name]
        return b.atomic_rmw(op, p, vals[0], order)

    def method_call(self, e: MethodCall) -> ir.Value:
        b = self.b
        if getattr(e, "simd", None):
            return simd.call(self, e)
        if getattr(e, "dyn_index", None) is not None:
            return self.with_temps(e, lambda: self.dyn_call(e))
        if getattr(e, "func_key", None):
            return self.call(e)  # type: ignore[arg-type]
        if getattr(e, "is_indirect", False):
            return self.indirect_call(e, e.args)
        if getattr(e, "owner", None) == "str":
            if e.method == "to_string":
                return self.b.call(self.funcs["string_from"], [self.expr(e.obj)])
            if e.method == "len":
                return self.b.extract_value(self.expr(e.obj), 1)
        if e.ctor_enum is not None:
            return self.aggregate_variant(e.ctor_enum, e.method, e.args, e)
        skey = getattr(e, "static_key", None)
        if skey is not None:  # associated function `Type.name(args)`
            def static() -> ir.Value:
                ptys = getattr(e, "param_tys", [])
                modes = e.arg_modes
                sargs = [self.call_arg(a, ptys[i] if i < len(ptys) else None,
                                       mode=modes[i] if i < len(modes) else "") for i, a in enumerate(e.args)]
                k = func_cname(skey)
                return b.call(self.funcs[k], self.expand_args(k, sargs))
            return self.with_temps(e, static)
        builtin = getattr(e, "builtin", None)
        if builtin == "clone":
            return self.clone_val(self.base_val(e.obj), e.owner)
        if builtin == "vec_get":
            val = self.base_val(e.obj)
            ptr, ln = b.extract_value(val, 0), b.extract_value(val, 1)
            idx = self.to_i64(self.expr(e.args[0]), e.args[0].ty)
            if not self.unchecked:
                self._bounds(idx, ln, e)
            elem = b.gep(ptr, [idx], inbounds=True)
            return elem if getattr(e, "view_ptr", False) else b.load(elem)
        if builtin == "vec_as_str":
            val = self.base_val(e.obj)
            res = ir.Constant(self.llty("str"), ir.Undefined)
            res = b.insert_value(res, b.extract_value(val, 0), 0)
            return b.insert_value(res, b.extract_value(val, 1), 1)
        if builtin in ("vec_swap", "vec_swap_remove", "vec_remove", "vec_insert"):
            return self.vec_edit(e, builtin[len("vec_"):])
        if builtin is not None:
            op = builtin[len("vec_"):]
            args = [self.base_addr(e.obj)] + [self.expr(a) for a in e.args]
            return b.call(self.vec_fn(e.owner or "", op), args)
        def method() -> ir.Value:
            recv = self.borrow_arg(e.obj) if e.self_lend else self.expr(e.obj)
            param_tys = getattr(e, "param_tys", [])
            modes = e.arg_modes
            args = [recv] + [self.call_arg(a, param_tys[i] if i < len(param_tys) else None,
                                           mode=modes[i] if i < len(modes) else "") for i, a in enumerate(e.args)]
            key = func_cname(getattr(e, "method_key", None) or f"{e.owner}.{e.method}")
            return b.call(self.funcs[key], self.expand_args(key, args))
        return self.with_temps(e, method)

    def try_expr(self, e: Try) -> ir.Value:
        b = self.b
        assert e.operand_ty is not None and e.ret_ty is not None
        oty, rty = e.operand_ty, e.ret_ty
        slot = self.alloca(self.llty(oty))
        b.store(self.expr(e.operand), slot)
        is_result = generic_parts(oty)[0] == "Result"  # type: ignore[index]
        bad_name, good_name = ("Err", "Ok") if is_result else ("None", "Valid")
        oinfo, rinfo = self.program.enum_infos[oty], self.program.enum_infos[rty]
        tag = b.load(b.gep(slot, [ir.Constant(I32, 0), ir.Constant(I32, 0)], inbounds=True))
        err, ok = self.new_block("try_err"), self.new_block("try_ok")
        b.cbranch(b.icmp_signed("==", tag, ir.Constant(I32, self.tag_index(oinfo, bad_name))), err, ok)
        self.at(err)
        out = self.alloca(self.llty(rty))
        b.store(ir.Constant(I32, self.tag_index(rinfo, bad_name)),
                b.gep(out, [ir.Constant(I32, 0), ir.Constant(I32, 0)], inbounds=True))
        if is_result:
            perr = b.load(self.payload_ptr(slot, oty, "Err", 0))
            if getattr(e, "from_fn", None):  # `?` converts the error with `fn Target.from(e: Source)`
                perr = b.call(self.funcs[func_cname(e.from_fn)], [perr])
            b.store(perr, self.payload_ptr(out, rty, "Err", 0))
        res = b.load(out)
        if self.has_owned():
            self.emit_drops(0)
        if self.in_main or self.cur_ret == "void":
            b.ret_void()
        else:
            b.ret(res)
        self.at(ok)
        return b.load(self.payload_ptr(slot, oty, good_name, 0))

    def _flatten_format_parts(self, parts: list[Expr]) -> list[Expr]:
        res: list[Expr] = []
        for p in parts:
            if isinstance(p, FormatStr):
                res.extend(self._flatten_format_parts(p.parts))
            elif isinstance(p, Binary) and p.op == "+" and getattr(p, "ty", None) == "string":
                res.extend(self._flatten_format_parts([p.left, p.right]))
            else:
                res.append(p)
        return res

    def reserve_text(self, out: ir.Value, parts: list[Expr]) -> None:
        """Grows the `string` at `out` once for an f-string's parts: the literal bytes plus room for each value
        (20 for an integer, 24 for a float, 16 for anything else), so short results need no regrowth."""
        guess = 0
        for p in parts:
            pty = int_base(getattr(p, "ty", "str"))
            if isinstance(p, StrLit):
                guess += len(p.value.encode("utf-8"))
            else:
                guess += 20 if pty in BITS else 24 if pty in FLOATS else 16
        if guess:
            lst = self.b.gep(out, [ir.Constant(I32, 0), ir.Constant(I32, 0)], inbounds=True)
            self.b.call(self.vec_fn("List[u8]", "reserve"), [lst, ir.Constant(I64, guess)])

    def format_str(self, e: FormatStr) -> ir.Value:
        b = self.b
        res_ptr = self.alloca(self.llty("string"), "fmt_res")
        b.store(b.call(self.funcs["string_new"], []), res_ptr)
        parts = self._flatten_format_parts(e.parts)
        self.reserve_text(res_ptr, parts)
        for p in parts:
            pty = int_base(getattr(p, "ty", "str"))
            v = self.expr(p)
            self.append_value(res_ptr, v, pty)
            if self.nd(pty) and self.is_temp(p):
                b.call(self.drop_fn(pty), [v])
        return b.load(res_ptr)

    def str_view(self, v: ir.Value, ty: str) -> ir.Value:
        """`str` view of a `str` or `string` value."""
        if ty == "str":
            return v
        b = self.b
        bytes_list = b.extract_value(v, 0)
        out = b.insert_value(ir.Constant(self.llty("str"), ir.Undefined), b.extract_value(bytes_list, 0), 0)
        return b.insert_value(out, b.extract_value(bytes_list, 1), 1)

    def append_text(self, out: ir.Value, text: str) -> None:
        self.b.call(self.funcs["string_append_str"], [out, self.str_const(text)])

    def append_value(self, out: ir.Value, v: ir.Value, ty: str, nested: bool = False) -> None:
        """Appends the printed form of `v` to the `string` at `out`. `nested` quotes text (inside a list or a
        struct). Integers, floats, and `bool` print as `print` does; other types go through `show_fn`."""
        b = self.b
        ty = int_base(ty)
        if ty in ("str", "string"):
            if nested:
                self.append_text(out, '"')
            b.call(self.funcs["string_append_str"], [out, self.str_view(v, ty)])
            if nested:
                self.append_text(out, '"')
        elif ty in SIGNED:
            b.call(self.funcs["string_append_i64"], [out, self.to_i64(v, ty)])
        elif ty in BITS and ty != "bool":
            b.call(self.funcs["string_append_u64"], [out, self.to_i64(v, ty)])
        elif ty == "bool":
            b.call(self.funcs["string_append_bool"], [out, v])
        elif ty in ("f32", "f64"):
            fval = b.fpext(v, F64) if ty == "f32" else v
            buf = self.alloca(ir.ArrayType(I8, 64), "flt_buf")
            buf_ptr = b.gep(buf, [ir.Constant(I32, 0), ir.Constant(I32, 0)], inbounds=True)
            snprintf_fn = self.c_fn("snprintf", I32, [I8P, self.size_t, I8P], var_arg=True)
            n_written = b.call(snprintf_fn, [buf_ptr, ir.Constant(self.size_t, 64), self.cstr("%.15g"), fval])
            view = b.insert_value(ir.Constant(self.llty("str"), ir.Undefined), buf_ptr, 0)
            view = b.insert_value(view, b.sext(n_written, I64), 1)
            b.call(self.funcs["string_append_str"], [out, view])
        elif ty in simd.SIMD_TYPES:
            simd.show(self, out, v, ty)
        else:
            b.call(self.show_fn(ty), [out, v])

    def call_to_string(self, key: str, v: ir.Value) -> ir.Value:
        """Calls a user `to_string(self)`; a `read self` takes the address of a temporary copy."""
        fn = self.funcs[key]
        want = fn.function_type.args[0]
        if want != v.type and isinstance(want, ir.PointerType):
            slot = self.alloca(v.type, "show_self")
            self.b.store(v, slot)
            v = slot
        return self.b.call(fn, [v])

    def show_fn(self, ty: str) -> ir.Function:
        """`gg_show_T(out: *string, v: T)`: appends `Point { x: 1, y: 2 }`, `[1, 2, 3]`, `Valid(3)` ...
        A type with its own `to_string` method prints through it. The value is only read, never dropped."""
        fn = self.shows.get(ty)
        if fn is not None:
            return fn
        sp = self.llty("string").as_pointer()
        fn = ir.Function(self.mod, ir.FunctionType(VOID, [sp, self.llty(ty)]), "gg_show_" + self._ident(ty))
        fn.linkage = "internal"
        self.shows[ty] = fn
        with self.func_ctx(fn):
            b = self.b
            out, v = fn.args

            def items(n: ir.Value, at: Callable[[ir.Value], ir.Value], elem: str) -> None:
                self.append_text(out, "[")

                def one(i: ir.Value) -> None:
                    first, rest = self.new_block("first"), self.new_block("rest")
                    b.cbranch(b.icmp_unsigned("==", i, ir.Constant(I64, 0)), first, rest)
                    self.at(rest)
                    self.append_text(out, ", ")
                    b.branch(first)
                    self.at(first)
                    self.append_value(out, b.load(at(i)), elem, nested=True)
                self.loop_n(n, one)
                self.append_text(out, "]")

            hk = heap_kind(ty)
            to_str = func_cname(f"{ty}.to_string")
            if to_str in self.funcs and hk is None:
                s = self.call_to_string(to_str, v)
                self.append_value(out, s, "string")
                if self.nd("string"):
                    b.call(self.drop_fn("string"), [s])
            elif hk == "List" or is_slice_type(ty):
                elem = heap_inner(ty) if hk == "List" else slice_elem_type(ty)
                p = b.extract_value(v, 0)
                items(b.extract_value(v, 1), lambda i: b.gep(p, [i], inbounds=True), elem)
            elif is_array_type(ty):
                n, elem = array_info(ty)
                slot = self.alloca(v.type, "show_arr")
                b.store(v, slot)
                items(ir.Constant(I64, n), lambda i: b.gep(slot, [ir.Constant(I32, 0), i], inbounds=True), elem)
            elif hk in ("Box", "Shared", "Arc"):
                inner = heap_inner(ty)
                p = b.extract_value(v, 0)
                nz, null, done = self.new_block("nz"), self.new_block("null"), self.new_block("done")
                b.cbranch(b.icmp_unsigned("!=", p, ir.Constant(p.type, None)), nz, null)
                self.at(null)
                self.append_text(out, "null")
                b.branch(done)
                self.at(nz)
                q = p if hk == "Box" else b.gep(p, [ir.Constant(I32, 0), ir.Constant(I32, 1)], inbounds=True)
                self.append_value(out, b.load(q), inner, nested=True)
                b.branch(done)
                self.at(done)
            elif ty in self.program.struct_infos:
                info = self.program.struct_infos[ty]
                name = info.decl.name
                tuple_like = getattr(info.decl, "from_prelude", False) and name.startswith("Tuple")
                self.append_text(out, "(" if tuple_like else name + " {" + (" " if info.fields else ""))
                for i, (fname, fty) in enumerate(info.fields.items()):
                    if i:
                        self.append_text(out, ", ")
                    if not tuple_like:
                        self.append_text(out, fname + ": ")
                    fv = b.extract_value(v, i)
                    if fname in info.field_modes:
                        fv = b.load(fv)
                    self.append_value(out, fv, fty, nested=True)
                self.append_text(out, ")" if tuple_like else (" }" if info.fields else "}"))
            else:
                info = self.program.enum_infos[ty]
                prefix = "" if getattr(info.decl, "from_prelude", False) else info.decl.name + "."
                slot = self.alloca(v.type, "show_enum")
                b.store(v, slot)
                tag = b.load(b.gep(slot, [ir.Constant(I32, 0), ir.Constant(I32, 0)]))
                done = self.new_block("done")
                for vi, (vname, vinfo) in enumerate(info.variants.items()):
                    yes, nxt = self.new_block("v"), self.new_block("n")
                    b.cbranch(b.icmp_signed("==", tag, ir.Constant(I32, vi)), yes, nxt)
                    self.at(yes)
                    self.append_text(out, prefix + vname + ("(" if vinfo.payload else ""))
                    for j, pt in enumerate(vinfo.payload):
                        if j:
                            self.append_text(out, ", ")
                        self.append_value(out, b.load(self.payload_ptr(slot, ty, vname, j)), pt, nested=True)
                    if vinfo.payload:
                        self.append_text(out, ")")
                    b.branch(done)
                    self.at(nxt)
                b.branch(done)
                self.at(done)
            b.ret_void()
            self.finish_entry()
        return fn

    def _spill_call(self, fn: ir.Function, vals: list[ir.Value]) -> ir.Value:
        """Calls a user method; a `read` parameter takes the address of a temporary copy."""
        args = []
        for want, v in zip(fn.function_type.args, vals):
            if want != v.type and isinstance(want, ir.PointerType):
                slot = self.alloca(v.type, "arg")
                self.b.store(v, slot)
                v = slot
            args.append(v)
        return self.b.call(fn, args)

    def _string_view(self, v: ir.Value) -> ir.Value:
        """The `str` view of a `string` value (its byte list)."""
        lst = self.b.extract_value(v, 0)
        sv = ir.Constant(self.llty("str"), ir.Undefined)
        sv = self.b.insert_value(sv, self.b.extract_value(lst, 0), 0)
        return self.b.insert_value(sv, self.b.extract_value(lst, 1), 1)

    def _items_of(self, v: ir.Value, ty: str) -> tuple[ir.Value, Callable[[ir.Value], ir.Value], str]:
        """(count, element address, element type) of a list, slice, or array value."""
        b = self.b
        if is_array_type(ty):
            n, elem = array_info(ty)
            slot = self.alloca(v.type, "items")
            b.store(v, slot)
            return ir.Constant(I64, n), lambda i: b.gep(slot, [ir.Constant(I32, 0), i], inbounds=True), elem
        elem = heap_inner(ty) if heap_kind(ty) == "List" else slice_elem_type(ty)
        p = b.extract_value(v, 0)
        return b.extract_value(v, 1), lambda i: b.gep(p, [i], inbounds=True), elem

    def eq_fn(self, ty: str) -> ir.Function:
        """`gg_eq_T(a: T, b: T) -> bool`: `==` field by field, element by element, variant and payload.
        A type with its own `eq` method compares through it. The values are only read, never dropped."""
        fn = self.eqs.get(ty)
        if fn is not None:
            return fn
        fn = ir.Function(self.mod, ir.FunctionType(I1, [self.llty(ty), self.llty(ty)]), "gg_eq_" + self._ident(ty))
        fn.linkage = "internal"
        self.eqs[ty] = fn
        with self.func_ctx(fn):
            b = self.b
            l, r = fn.args
            no = self.new_block("ne")

            def same(x: ir.Value, y: ir.Value, t: str) -> None:
                """Continue only when `x == y`; otherwise jump to `no`."""
                ok = self.eq_values(x, y, t)
                yes = self.new_block("eq")
                b.cbranch(ok, yes, no)
                self.at(yes)

            hk = heap_kind(ty)
            own = func_cname(f"{ty}.eq")
            if own in self.funcs and ty != "string":
                b.ret(self._spill_call(self.funcs[own], [l, r]))
            elif hk == "List" or is_slice_type(ty) or is_array_type(ty):
                n, at_l, elem = self._items_of(l, ty)
                m, at_r, _ = self._items_of(r, ty)
                same(n, m, "usize")
                self.loop_n(n, lambda i: same(b.load(at_l(i)), b.load(at_r(i)), elem))
                b.ret(ir.Constant(I1, 1))
            elif hk in ("Box", "Shared", "Arc"):
                inner = heap_inner(ty)
                pl, pr = b.extract_value(l, 0), b.extract_value(r, 0)
                if hk != "Box":
                    pl = b.gep(pl, [ir.Constant(I32, 0), ir.Constant(I32, 1)], inbounds=True)
                    pr = b.gep(pr, [ir.Constant(I32, 0), ir.Constant(I32, 1)], inbounds=True)
                b.ret(self.eq_values(b.load(pl), b.load(pr), inner))
            elif ty in self.program.struct_infos:
                info = self.program.struct_infos[ty]
                for i, (fname, fty) in enumerate(info.fields.items()):
                    fl, fr = b.extract_value(l, i), b.extract_value(r, i)
                    if fname in info.field_modes:
                        fl, fr = b.load(fl), b.load(fr)
                    same(fl, fr, fty)
                b.ret(ir.Constant(I1, 1))
            else:
                info = self.program.enum_infos[ty]
                sl, sr = self.alloca(l.type, "eq_l"), self.alloca(r.type, "eq_r")
                b.store(l, sl)
                b.store(r, sr)
                tag = b.load(b.gep(sl, [ir.Constant(I32, 0), ir.Constant(I32, 0)]))
                same(tag, b.load(b.gep(sr, [ir.Constant(I32, 0), ir.Constant(I32, 0)])), "i32")
                for vi, (vname, vinfo) in enumerate(info.variants.items()):
                    if not vinfo.payload:
                        continue
                    yes, nxt = self.new_block("v"), self.new_block("n")
                    b.cbranch(b.icmp_signed("==", tag, ir.Constant(I32, vi)), yes, nxt)
                    self.at(yes)
                    for j, pt in enumerate(vinfo.payload):
                        same(b.load(self.payload_ptr(sl, ty, vname, j)), b.load(self.payload_ptr(sr, ty, vname, j)), pt)
                    b.ret(ir.Constant(I1, 1))
                    self.at(nxt)
                b.ret(ir.Constant(I1, 1))
            self.at(no)
            b.ret(ir.Constant(I1, 0))
            self.finish_entry()
        return fn

    def eq_values(self, x: ir.Value, y: ir.Value, ty: str) -> ir.Value:
        """`x == y` for any type `==` accepts."""
        ty = int_base(ty)
        if ty == "string":
            return self.b.call(self.rt_str_eq(), [self._string_view(x), self._string_view(y)])
        if ty in BITS or ty in FLOATS or ty in ("bool", "str"):
            return self.compare("==", ty, x, y)
        if is_ptr_type(ty):
            return self.b.icmp_unsigned("==", x, y)
        return self.b.call(self.eq_fn(ty), [x, y])

    def rt_mix64(self) -> ir.Function:
        fn, new = self._runtime("mix64", I64, [I64])
        if new:
            with self.func_ctx(fn):
                b = self.b
                h = fn.args[0]
                for k in (0xFF51AFD7ED558CCD, 0xC4CEB9FE1A85EC53):
                    h = b.mul(b.xor(h, b.lshr(h, ir.Constant(I64, 33))), ir.Constant(I64, k))
                b.ret(b.xor(h, b.lshr(h, ir.Constant(I64, 33))))
                self.finish_entry()
        return fn

    def rt_hash_str(self) -> ir.Function:
        fn, new = self._runtime("hash_str", I64, [self.llty("str")])
        if new:
            with self.func_ctx(fn):
                # Eight bytes per step. The last 1..7 bytes are read as one word: with overlapping
                # loads when the text has 4 or more bytes, else as the first, middle, and last byte.
                b = self.b
                s = fn.args[0]
                p, n = b.extract_value(s, 0), b.extract_value(s, 1)
                c = lambda v: ir.Constant(I64, v)

                def word(off: ir.Value, ty: ir.IntType) -> ir.Value:
                    q = b.bitcast(b.gep(p, [off], inbounds=True), ty.as_pointer())
                    v = b.load(q, align=1)
                    return v if ty is I64 else b.zext(v, I64)

                def step(h: ir.Value, w: ir.Value) -> ir.Value:
                    t = b.mul(b.xor(h, w), c(0x9E3779B97F4A7C15))
                    return b.xor(t, b.lshr(t, c(32)))

                h, i = self.alloca(I64, "h"), self.alloca(I64, "i")
                b.store(b.xor(c(0xCBF29CE484222325), n), h)
                b.store(c(0), i)
                head, body, tail, out = (self.new_block(x) for x in ("wh", "wb", "tail", "out"))
                b.branch(head)
                self.at(head)
                iv = b.load(i)
                b.cbranch(b.icmp_unsigned("<=", b.add(iv, c(8)), n), body, tail)
                self.at(body)
                b.store(step(b.load(h), word(iv, I64)), h)
                b.store(b.add(iv, c(8)), i)
                b.branch(head)
                self.at(tail)
                rem = b.sub(n, iv)
                some, long, mid, four, short, mix = (self.new_block(x) for x in
                                                     ("some", "long", "mid", "four", "short", "mix"))
                b.cbranch(b.icmp_unsigned("==", rem, c(0)), out, some)
                self.at(some)
                b.cbranch(b.icmp_unsigned(">=", n, c(8)), long, mid)
                self.at(long)
                w_long = word(b.sub(n, c(8)), I64)
                b.branch(mix)
                self.at(mid)
                b.cbranch(b.icmp_unsigned(">=", n, c(4)), four, short)
                self.at(four)
                w_four = b.or_(word(c(0), I32), b.shl(word(b.sub(n, c(4)), I32), c(32)))
                b.branch(mix)
                self.at(short)
                byte = lambda off: b.zext(b.load(b.gep(p, [off], inbounds=True)), I64)
                w_short = b.or_(b.or_(byte(c(0)), b.shl(byte(b.lshr(n, c(1))), c(8))),
                                b.shl(byte(b.sub(n, c(1))), c(16)))
                b.branch(mix)
                self.at(mix)
                w = b.phi(I64)
                w.add_incoming(w_long, long)
                w.add_incoming(w_four, four)
                w.add_incoming(w_short, short)
                b.store(step(b.load(h), w), h)
                b.branch(out)
                self.at(out)
                b.ret(b.call(self.rt_mix64(), [b.load(h)]))
                self.finish_entry()
        return fn

    def hash_fn(self, ty: str) -> ir.Function:
        """`gg_hash_T(v: T) -> u64`: mixes the hashes of the fields, elements, or variant and payload.
        A type with its own `hash` method hashes through it."""
        fn = self.hashes.get(ty)
        if fn is not None:
            return fn
        fn = ir.Function(self.mod, ir.FunctionType(I64, [self.llty(ty)]), "gg_hash_" + self._ident(ty))
        fn.linkage = "internal"
        self.hashes[ty] = fn
        with self.func_ctx(fn):
            b = self.b
            v = fn.args[0]
            h = self.alloca(I64, "h")
            b.store(ir.Constant(I64, 0x9E3779B97F4A7C15), h)

            def mix(x: ir.Value, t: str) -> None:
                cur = b.load(h)
                part = self.hash_value(x, t)
                b.store(b.call(self.rt_mix64(), [b.xor(b.add(cur, ir.Constant(I64, 0x9E3779B97F4A7C15)), part)]), h)

            hk = heap_kind(ty)
            own = func_cname(f"{ty}.hash")
            if own in self.funcs and ty != "string":
                b.store(self._spill_call(self.funcs[own], [v]), h)
            elif hk == "List" or is_slice_type(ty) or is_array_type(ty):
                n, at, elem = self._items_of(v, ty)
                mix(n, "usize")
                self.loop_n(n, lambda i: mix(b.load(at(i)), elem))
            elif hk in ("Box", "Shared", "Arc"):
                p = b.extract_value(v, 0)
                if hk != "Box":
                    p = b.gep(p, [ir.Constant(I32, 0), ir.Constant(I32, 1)], inbounds=True)
                mix(b.load(p), heap_inner(ty))
            elif ty in self.program.struct_infos:
                info = self.program.struct_infos[ty]
                for i, (fname, fty) in enumerate(info.fields.items()):
                    fv = b.extract_value(v, i)
                    mix(b.load(fv) if fname in info.field_modes else fv, fty)
            else:
                info = self.program.enum_infos[ty]
                slot = self.alloca(v.type, "hash_enum")
                b.store(v, slot)
                tag = b.load(b.gep(slot, [ir.Constant(I32, 0), ir.Constant(I32, 0)]))
                mix(tag, "i32")
                done = self.new_block("done")
                for vi, (vname, vinfo) in enumerate(info.variants.items()):
                    if not vinfo.payload:
                        continue
                    yes, nxt = self.new_block("v"), self.new_block("n")
                    b.cbranch(b.icmp_signed("==", tag, ir.Constant(I32, vi)), yes, nxt)
                    self.at(yes)
                    for j, pt in enumerate(vinfo.payload):
                        mix(b.load(self.payload_ptr(slot, ty, vname, j)), pt)
                    b.branch(done)
                    self.at(nxt)
                b.branch(done)
                self.at(done)
            b.ret(b.load(h))
            self.finish_entry()
        return fn

    def hash_value(self, x: ir.Value, ty: str) -> ir.Value:
        """`hash(x)` for any type `hash` accepts."""
        b = self.b
        ty = int_base(ty)
        if ty == "string":
            return b.call(self.rt_hash_str(), [self._string_view(x)])
        if ty == "str":
            return b.call(self.rt_hash_str(), [x])
        if ty in BITS:
            wide = x if BITS[ty] == 64 else (b.sext(x, I64) if ty in SIGNED else b.zext(x, I64))
            return b.call(self.rt_mix64(), [wide])
        if ty == "bool":
            return b.call(self.rt_mix64(), [b.zext(x, I64)])
        if is_ptr_type(ty):
            return b.call(self.rt_mix64(), [b.ptrtoint(x, I64)])
        return b.call(self.hash_fn(ty), [x])

    # -- JSON: `to_json(x)` and `from_json[T](text)` --------------------------------------------
    def core_call(self, key: str, args: list[ir.Value]) -> ir.Value:
        """Calls a Core library function by its key (`_JsonReader.next_key`)."""
        return self.b.call(self.funcs[func_cname(key)], args)

    def json_call(self, e: Call) -> ir.Value:
        b = self.b
        ty = e.json_ty  # type: ignore[attr-defined]
        if not getattr(e, "json_decode", False):
            out = self.alloca(self.llty("string"), "json")
            b.store(b.call(self.funcs[func_cname("string.new")], []), out)
            b.call(self.json_fn(ty), [out, self.base_val(e.args[0])])
            return b.load(out)
        rty = e.ty or ""
        reader = self.alloca(self.llty("_JsonReader"), "json_reader")
        b.store(self.core_call("_JsonReader.new", [self.expr(e.args[0])]), reader)
        slot = self.alloca(self.llty(ty), "json_value")
        b.store(ir.Constant(self.llty(ty), None), slot)  # zero bytes: a value every drop accepts
        ok = b.call(self.json_dec_fn(ty), [reader, slot])
        done = b.and_(ok, self.core_call("_JsonReader.finish", [reader]))
        res = self.alloca(self.llty(rty), "json_result")
        info = self.program.enum_infos[rty]
        good, bad, end = self.new_block("json_ok"), self.new_block("json_err"), self.new_block("json_end")
        b.cbranch(done, good, bad)
        self.at(good)
        b.store(ir.Constant(I32, self.tag_index(info, "Ok")), b.gep(res, [ir.Constant(I32, 0), ir.Constant(I32, 0)]))
        b.store(b.load(slot), self.payload_ptr(res, rty, "Ok", 0))
        b.branch(end)
        self.at(bad)
        if self.nd(ty):
            b.call(self.drop_fn(ty), [b.load(slot)])
        b.store(ir.Constant(I32, self.tag_index(info, "Err")), b.gep(res, [ir.Constant(I32, 0), ir.Constant(I32, 0)]))
        err_field = list(self.program.struct_infos["_JsonReader"].fields).index("error")
        err_ptr = b.gep(reader, [ir.Constant(I32, 0), ir.Constant(I32, err_field)], inbounds=True)
        b.store(b.load(err_ptr), self.payload_ptr(res, rty, "Err", 0))  # the message moves into the result
        b.store(b.call(self.funcs[func_cname("string.new")], []), err_ptr)
        b.branch(end)
        self.at(end)
        b.call(self.drop_fn("_JsonReader"), [b.load(reader)])
        return b.load(res)

    def json_fn(self, ty: str) -> ir.Function:
        """`gg_json_T(out: *string, v: T)`: appends the JSON text of `v`. Structs are objects, enums
        `"Name"` or `{"Name": payload}`, `Optional` a value or `null`, lists, arrays, and tuples arrays."""
        fn = self.jsons.get(ty)
        if fn is not None:
            return fn
        sp = self.llty("string").as_pointer()
        fn = ir.Function(self.mod, ir.FunctionType(VOID, [sp, self.llty(ty)]), "gg_json_" + self._ident(ty))
        fn.linkage = "internal"
        self.jsons[ty] = fn
        with self.func_ctx(fn):
            b = self.b
            out, v = fn.args

            def items(n: ir.Value, at: Callable[[ir.Value], ir.Value], elem: str) -> None:
                self.append_text(out, "[")

                def one(i: ir.Value) -> None:
                    first, rest = self.new_block("first"), self.new_block("rest")
                    b.cbranch(b.icmp_unsigned("==", i, ir.Constant(I64, 0)), first, rest)
                    self.at(rest)
                    self.append_text(out, ",")
                    b.branch(first)
                    self.at(first)
                    self.json_value(out, b.load(at(i)), elem)
                self.loop_n(n, one)
                self.append_text(out, "]")

            hk = heap_kind(ty)
            own = func_cname(f"{ty}.to_json")
            if own in self.funcs and hk is None:
                s = self.call_to_string(own, v)
                self.append_value(out, s, "string")
                b.call(self.drop_fn("string"), [s])
            elif hk == "List" or is_slice_type(ty) or is_array_type(ty):
                n, at, elem = self._items_of(v, ty)
                items(n, at, elem)
            elif hk in ("Box", "Shared", "Arc"):
                p = b.extract_value(v, 0)
                if hk != "Box":
                    p = b.gep(p, [ir.Constant(I32, 0), ir.Constant(I32, 1)], inbounds=True)
                self.json_value(out, b.load(p), heap_inner(ty))
            elif ty in self.program.struct_infos:
                info = self.program.struct_infos[ty]
                tuple_like = getattr(info.decl, "from_prelude", False) and info.decl.name.startswith("Tuple")
                self.append_text(out, "[" if tuple_like else "{")
                for i, (fname, fty) in enumerate(info.fields.items()):
                    if i:
                        self.append_text(out, ",")
                    if not tuple_like:
                        self.core_call("_json_escape", [out, self.str_const(fname)])
                        self.append_text(out, ":")
                    self.json_value(out, b.extract_value(v, i), fty)
                self.append_text(out, "]" if tuple_like else "}")
            else:
                info = self.program.enum_infos[ty]
                optional = getattr(info.decl, "from_prelude", False) and info.decl.name == "Optional"
                slot = self.alloca(v.type, "json_enum")
                b.store(v, slot)
                tag = b.load(b.gep(slot, [ir.Constant(I32, 0), ir.Constant(I32, 0)]))
                done = self.new_block("done")
                for vi, (vname, vinfo) in enumerate(info.variants.items()):
                    yes, nxt = self.new_block("v"), self.new_block("n")
                    b.cbranch(b.icmp_signed("==", tag, ir.Constant(I32, vi)), yes, nxt)
                    self.at(yes)
                    if optional:
                        if vinfo.payload:
                            self.json_value(out, b.load(self.payload_ptr(slot, ty, vname, 0)), vinfo.payload[0])
                        else:
                            self.append_text(out, "null")
                    elif not vinfo.payload:
                        self.core_call("_json_escape", [out, self.str_const(vname)])
                    else:
                        self.append_text(out, "{")
                        self.core_call("_json_escape", [out, self.str_const(vname)])
                        self.append_text(out, ":")
                        many = len(vinfo.payload) > 1
                        if many:
                            self.append_text(out, "[")
                        for j, pt in enumerate(vinfo.payload):
                            if j:
                                self.append_text(out, ",")
                            self.json_value(out, b.load(self.payload_ptr(slot, ty, vname, j)), pt)
                        self.append_text(out, "]}" if many else "}")
                    b.branch(done)
                    self.at(nxt)
                b.branch(done)
                self.at(done)
            b.ret_void()
            self.finish_entry()
        return fn

    def json_value(self, out: ir.Value, v: ir.Value, ty: str) -> None:
        ty = int_base(ty)
        if ty in ("str", "string"):
            self.core_call("_json_escape", [out, self.str_view(v, ty)])
        elif ty in ("f32", "f64"):
            self.core_call("_json_number", [out, self.b.fpext(v, F64) if ty == "f32" else v])
        elif ty in BITS or ty == "bool":
            self.append_value(out, v, ty)
        else:
            self.b.call(self.json_fn(ty), [out, v])

    def json_dec_fn(self, ty: str) -> ir.Function:
        """`gg_jdec_T(r: *_JsonReader, out: *T) -> bool`: reads one JSON value into `*out`, which starts
        as zero bytes. On a failure the reader holds the message and `*out` can still be dropped."""
        fn = self.jdecs.get(ty)
        if fn is not None:
            return fn
        rp = self.llty("_JsonReader").as_pointer()
        fn = ir.Function(self.mod, ir.FunctionType(I1, [rp, self.llty(ty).as_pointer()]), "gg_jdec_" + self._ident(ty))
        fn.linkage = "internal"
        self.jdecs[ty] = fn
        with self.func_ctx(fn):
            b = self.b
            r, out = fn.args
            t = int_base(ty)
            hk = heap_kind(t)
            fail = self.new_block("fail")

            def ok_or_fail(cond: ir.Value) -> None:
                go = self.new_block("go")
                b.cbranch(cond, go, fail)
                self.at(go)

            def failed() -> ir.Value:
                return self.core_call("_JsonReader.failed", [r])

            def ret_ok() -> None:
                b.ret(b.not_(failed()))

            def fail_with(msg: str) -> None:
                self.core_call("_JsonReader.fail", [r, self.str_const(msg)])
                b.ret(ir.Constant(I1, 0))

            def items(count_fixed: int | None, at: Callable[[ir.Value], ir.Value], elem: str,
                      push: Callable[[ir.Value], None] | None) -> None:
                ok_or_fail(self.core_call("_JsonReader.begin_array", [r]))
                first = self.alloca(I1, "first")
                b.store(ir.Constant(I1, 1), first)
                idx = self.alloca(I64, "idx")
                b.store(ir.Constant(I64, 0), idx)
                head, body, after = self.new_block("ah"), self.new_block("ab"), self.new_block("aa")
                b.branch(head)
                self.at(head)
                more = self.core_call("_JsonReader.next_item", [r, b.load(first)])
                b.cbranch(more, body, after)
                self.at(body)
                b.store(ir.Constant(I1, 0), first)
                i = b.load(idx)
                if push is None:  # an array: exactly `count_fixed` elements
                    room, over = self.new_block("room"), self.new_block("over")
                    b.cbranch(b.icmp_unsigned("<", i, ir.Constant(I64, count_fixed or 0)), room, over)
                    self.at(over)
                    fail_with("too many elements for the array")
                    self.at(room)
                    b.call(self.json_dec_fn(elem), [r, at(i)])
                else:
                    tmp = self.alloca(self.llty(elem), "elem")
                    b.store(ir.Constant(self.llty(elem), None), tmp)
                    b.call(self.json_dec_fn(elem), [r, tmp])
                    push(b.load(tmp))  # kept even after a failure: the list drops it
                b.store(b.add(i, ir.Constant(I64, 1)), idx)
                ok_or_fail(b.not_(failed()))
                b.branch(head)
                self.at(after)
                if count_fixed is not None:
                    full = self.new_block("full")
                    short = self.new_block("short")
                    b.cbranch(b.icmp_unsigned("==", b.load(idx), ir.Constant(I64, count_fixed)), full, short)
                    self.at(short)
                    fail_with(f"expected {count_fixed} elements")
                    self.at(full)
                ret_ok()

            if t in SIGNED:
                lo, hi = INT_RANGES[t]
                n = self.core_call("_JsonReader.read_int", [r, ir.Constant(I64, lo), ir.Constant(I64, hi)])
                b.store(b.trunc(n, self.llty(t)) if BITS[t] < 64 else n, out)
                ret_ok()
            elif t in BITS and t != "bool":
                n = self.core_call("_JsonReader.read_uint", [r, ir.Constant(I64, INT_RANGES[t][1])])
                b.store(b.trunc(n, self.llty(t)) if BITS[t] < 64 else n, out)
                ret_ok()
            elif t == "bool":
                b.store(self.core_call("_JsonReader.read_bool", [r]), out)
                ret_ok()
            elif t in ("f32", "f64"):
                x = self.core_call("_JsonReader.read_f64", [r])
                b.store(b.fptrunc(x, F32) if t == "f32" else x, out)
                ret_ok()
            elif t == "string":
                b.store(self.core_call("_JsonReader.read_string", [r]), out)
                ret_ok()
            elif hk == "List":
                elem = heap_inner(t)
                items(None, lambda i: i, elem, lambda val: b.call(self.vec_fn(t, "push"), [out, val]))
            elif is_array_type(t):
                n_el, elem = array_info(t)
                items(n_el, lambda i: b.gep(out, [ir.Constant(I32, 0), i], inbounds=True), elem, None)
            elif hk == "Box":
                inner = heap_inner(t)
                it = self.llty(inner)
                q = b.bitcast(b.call(self.rt_alloc(), [self.sizeof(it)]), it.as_pointer())
                b.store(ir.Constant(it, None), q)
                b.store(b.insert_value(ir.Constant(self.llty(t), ir.Undefined), q, 0), out)
                b.ret(b.call(self.json_dec_fn(inner), [r, q]))
            elif t in self.program.struct_infos:
                info = self.program.struct_infos[t]
                fields = list(info.fields.items())
                if getattr(info.decl, "from_prelude", False) and info.decl.name.startswith("Tuple"):
                    ok_or_fail(self.core_call("_JsonReader.begin_array", [r]))
                    for i, (_fname, fty) in enumerate(fields):
                        ok_or_fail(self.core_call("_JsonReader.next_item", [r, ir.Constant(I1, int(i == 0))]))
                        ok_or_fail(b.call(self.json_dec_fn(fty), [r, b.gep(out, [ir.Constant(I32, 0), ir.Constant(I32, i)], inbounds=True)]))
                    end_ok = self.core_call("_JsonReader.next_item", [r, ir.Constant(I1, 0)])
                    closed = self.new_block("closed")
                    extra = self.new_block("extra")
                    b.cbranch(end_ok, extra, closed)
                    self.at(extra)
                    fail_with(f"expected {len(fields)} elements")
                    self.at(closed)
                    ret_ok()
                else:
                    ok_or_fail(self.core_call("_JsonReader.begin_object", [r]))
                    seen = [self.alloca(I1, "seen_" + f) for f, _ in fields]
                    for s in seen:
                        b.store(ir.Constant(I1, 0), s)
                    first = self.alloca(I1, "first")
                    b.store(ir.Constant(I1, 1), first)
                    head, after = self.new_block("oh"), self.new_block("oa")
                    b.branch(head)
                    self.at(head)
                    body = self.new_block("ob")
                    b.cbranch(self.core_call("_JsonReader.next_key", [r, b.load(first)]), body, after)
                    self.at(body)
                    b.store(ir.Constant(I1, 0), first)
                    for i, (fname, fty) in enumerate(fields):
                        hit, miss = self.new_block("hit"), self.new_block("miss")
                        b.cbranch(self.core_call("_JsonReader.key_is", [r, self.str_const(fname)]), hit, miss)
                        self.at(hit)
                        dup, fresh = self.new_block("dup"), self.new_block("fresh")
                        b.cbranch(b.load(seen[i]), dup, fresh)
                        self.at(dup)
                        fail_with(f"field `{fname}` appears twice")
                        self.at(fresh)
                        b.store(ir.Constant(I1, 1), seen[i])
                        b.call(self.json_dec_fn(fty), [r, b.gep(out, [ir.Constant(I32, 0), ir.Constant(I32, i)], inbounds=True)])
                        b.branch(head)
                        self.at(miss)
                    self.core_call("_JsonReader.skip_value", [r])  # an unknown key
                    b.branch(head)
                    self.at(after)
                    ok_or_fail(b.not_(failed()))
                    for i, (fname, fty) in enumerate(fields):
                        have, missing = self.new_block("have"), self.new_block("missing")
                        b.cbranch(b.load(seen[i]), have, missing)
                        self.at(missing)
                        oinfo = self.program.enum_infos.get(int_base(fty))
                        if oinfo is not None and getattr(oinfo.decl, "from_prelude", False) and oinfo.decl.name == "Optional":
                            fp = b.gep(out, [ir.Constant(I32, 0), ir.Constant(I32, i)], inbounds=True)
                            b.store(ir.Constant(I32, self.tag_index(oinfo, "None")),
                                    b.gep(fp, [ir.Constant(I32, 0), ir.Constant(I32, 0)]))  # a missing Optional is None
                            b.branch(have)
                        else:
                            fail_with(f"missing field `{fname}`")
                        self.at(have)
                    ret_ok()
            else:
                info = self.program.enum_infos[t]
                variants = list(info.variants.items())
                tagp = b.gep(out, [ir.Constant(I32, 0), ir.Constant(I32, 0)])
                if getattr(info.decl, "from_prelude", False) and info.decl.name == "Optional":
                    none, some = self.new_block("none"), self.new_block("some")
                    b.cbranch(self.core_call("_JsonReader.read_null", [r]), none, some)
                    self.at(none)
                    b.store(ir.Constant(I32, self.tag_index(info, "None")), tagp)
                    ret_ok()
                    self.at(some)
                    b.store(ir.Constant(I32, self.tag_index(info, "Valid")), tagp)
                    b.ret(b.call(self.json_dec_fn(info.variants["Valid"].payload[0]),
                                 [r, self.payload_ptr(out, t, "Valid", 0)]))
                else:
                    name_form, obj_form = self.new_block("name"), self.new_block("obj")
                    quote = self.core_call("_JsonReader.peek", [r])
                    b.cbranch(b.icmp_unsigned("==", quote, ir.Constant(I8, ord('"'))), name_form, obj_form)
                    self.at(name_form)  # `"Red"`: a variant without payload
                    word = self.core_call("_JsonReader.read_string", [r])
                    view = self.str_view(word, "string")
                    for vi, (vname, vinfo) in enumerate(variants):
                        if vinfo.payload:
                            continue
                        hit, miss = self.new_block("hit"), self.new_block("miss")
                        b.cbranch(b.call(self.rt_str_eq(), [view, self.str_const(vname)]), hit, miss)
                        self.at(hit)
                        b.call(self.drop_fn("string"), [word])
                        b.store(ir.Constant(I32, vi), tagp)
                        ret_ok()
                        self.at(miss)
                    b.call(self.drop_fn("string"), [word])
                    fail_with(f"not a variant of {info.decl.name}")
                    self.at(obj_form)  # `{"Circle": 1.5}` or `{"Rect": [1, 2]}`
                    ok_or_fail(self.core_call("_JsonReader.begin_object", [r]))
                    ok_or_fail(self.core_call("_JsonReader.next_key", [r, ir.Constant(I1, 1)]))
                    for vi, (vname, vinfo) in enumerate(variants):
                        hit, miss = self.new_block("hit"), self.new_block("miss")
                        b.cbranch(self.core_call("_JsonReader.key_is", [r, self.str_const(vname)]), hit, miss)
                        self.at(hit)
                        b.store(ir.Constant(I32, vi), tagp)
                        if len(vinfo.payload) == 1:
                            ok_or_fail(b.call(self.json_dec_fn(vinfo.payload[0]), [r, self.payload_ptr(out, t, vname, 0)]))
                        elif vinfo.payload:
                            ok_or_fail(self.core_call("_JsonReader.begin_array", [r]))
                            for j, pt in enumerate(vinfo.payload):
                                ok_or_fail(self.core_call("_JsonReader.next_item", [r, ir.Constant(I1, int(j == 0))]))
                                ok_or_fail(b.call(self.json_dec_fn(pt), [r, self.payload_ptr(out, t, vname, j)]))
                            closed, extra = self.new_block("closed"), self.new_block("extra")
                            b.cbranch(self.core_call("_JsonReader.next_item", [r, ir.Constant(I1, 0)]), extra, closed)
                            self.at(extra)
                            fail_with(f"`{vname}` has {len(vinfo.payload)} values")
                            self.at(closed)
                        else:
                            ok_or_fail(self.core_call("_JsonReader.read_null", [r]))
                        end, extra = self.new_block("end"), self.new_block("extra")
                        b.cbranch(self.core_call("_JsonReader.next_key", [r, ir.Constant(I1, 0)]), extra, end)
                        self.at(extra)
                        fail_with("an enum object has one key, the variant")
                        self.at(end)
                        ret_ok()
                        self.at(miss)
                    fail_with(f"not a variant of {info.decl.name}")
            self.at(fail)
            b.ret(ir.Constant(I1, 0))
            self.finish_entry()
        return fn

    def print_call(self, call: Call, err: bool = False) -> ir.Value:
        self.need_os("eprint" if err else "print", call)
        b = self.b
        fmt: list[str] = []
        args: list[ir.Value] = []
        strings_to_drop: list[ir.Value] = []
        for i, a in enumerate(call.args):
            if i:
                fmt.append(" ")
            ty = int_base(a.ty or "i32")
            v = self.expr(a)
            if ty in ("i8", "i16", "i32"):
                fmt.append("%d")
                args.append(v if ty == "i32" else b.sext(v, I32))
            elif ty in ("u8", "u16", "u32"):
                fmt.append("%u")
                args.append(v if ty == "u32" else b.zext(v, I32))
            elif ty in ("i64", "isize"):
                fmt.append("%lld")
                args.append(v)
            elif ty in ("u64", "usize"):
                fmt.append("%llu")
                args.append(v)
            elif ty == "f32":
                fmt.append("%g")
                args.append(b.fpext(v, F64))
            elif ty == "f64":
                fmt.append("%.15g")
                args.append(v)
            elif ty == "bool":
                fmt.append("%s")
                args.append(b.select(v, self.cstr("true"), self.cstr("false")))
            elif ty == "str":
                fmt.append("%.*s")
                args += [b.trunc(b.extract_value(v, 1), I32), b.extract_value(v, 0)]
            elif ty == "string":
                fmt.append("%.*s")
                bytes_list = b.extract_value(v, 0)
                ptr = b.extract_value(bytes_list, 0)
                slen = b.extract_value(bytes_list, 1)
                args += [b.trunc(slen, I32), ptr]
                if self.nd("string") and self.is_temp(a):
                    strings_to_drop.append(v)
            else:  # struct, list, array, enum: built as a string first
                slot = self.alloca(self.llty("string"), "show_res")
                b.store(b.call(self.funcs["string_new"], []), slot)
                self.append_value(slot, v, ty)
                if self.nd(ty) and self.is_temp(a):
                    b.call(self.drop_fn(ty), [v])
                text_v = b.load(slot)
                bytes_list = b.extract_value(text_v, 0)
                fmt.append("%.*s")
                args += [b.trunc(b.extract_value(bytes_list, 1), I32), b.extract_value(bytes_list, 0)]
                strings_to_drop.append(text_v)
        fmt.append("\n")
        text = "".join(fmt).replace("\\", "\\\\")
        if err:
            res = self._write_stderr(text, args)
        else:
            res = b.call(self.c_fn("printf", I32, [I8P], var_arg=True), [self.cstr(text), *args])
        for sval in strings_to_drop:
            b.call(self.drop_fn("string"), [sval])
        return res

    def _write_stderr(self, fmt: str, args: list[ir.Value]) -> ir.Value:
        """Format `fmt` and write the bytes to file descriptor 2. Avoids the `stderr` macro."""
        b = self.b
        sn = self.c_fn("snprintf", I32, [I8P, self.size_t, I8P], var_arg=True)
        need = b.call(sn, [ir.Constant(I8P, None), ir.Constant(self.size_t, 0), self.cstr(fmt), *args])
        n64 = b.sext(need, I64)
        size = b.add(n64, ir.Constant(I64, 1))
        buf = b.call(self.c_fn("malloc", I8P, [I64]), [size])
        b.call(sn, [buf, size, self.cstr(fmt), *args])
        if self.windows:
            wr = self.c_fn("_write", I32, [I32, I8P, I32])
            b.call(wr, [ir.Constant(I32, 2), buf, need])
        else:
            wr = self.c_fn("write", I64, [I32, I8P, I64])
            b.call(wr, [ir.Constant(I32, 2), buf, n64])
        b.call(self.c_fn("free", VOID, [I8P]), [buf])
        return need

    def _emit_arg_runtime(self) -> None:
        """Save the process arguments and expose `gg_argc` / `gg_argv_at` to std.process."""
        g_argc = ir.GlobalVariable(self.mod, I32, "gg_argc_val")
        g_argc.linkage = "internal"
        g_argc.initializer = ir.Constant(I32, 0)
        argv_ty = I8P.as_pointer()
        g_argv = ir.GlobalVariable(self.mod, argv_ty, "gg_argv_val")
        g_argv.linkage = "internal"
        g_argv.initializer = ir.Constant(argv_ty, None)
        self._g_argc = g_argc
        self._g_argv = g_argv
        fn = self.c_fn("gg_argc", I32, [])
        if not fn.blocks:
            with self.func_ctx(fn):
                self.b.ret(self.b.load(g_argc))
                self.finish_entry()
        fn2 = self.c_fn("gg_argv_at", I8P, [I32])
        if not fn2.blocks:
            with self.func_ctx(fn2):
                argv = self.b.load(g_argv)
                self.b.ret(self.b.load(self.b.gep(argv, [fn2.args[0]])))
                self.finish_entry()


def generate_llvm(program: Program, filename: str = "<source>", release: bool = False, unchecked: bool = False,
                  target: str | None = None, leakcheck: bool = False, freestanding: bool = False,
                  debug: bool = False) -> str:
    """Generates LLVM IR text from type-checked program."""
    return LLVMGen(program, filename=filename, release=release, unchecked=unchecked, target=target,
                   leakcheck=leakcheck, freestanding=freestanding, debug=debug).generate()
