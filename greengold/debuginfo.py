"""Debug information (`gg build -g`): DWARF line tables, functions, and local variables.

A debugger then stops at Greengold lines, steps through them, shows `.gg` file and line in a stack
trace, and prints locals by name: numbers, `bool`, structs, enums (the tag names the variant and the payload
is a union of the variants), fixed arrays, raw pointers, `str` and slices `{ptr, len}`, `List[T]`
`{ptr, len, cap}`, `Box[T]`, `Shared[T]`/`Arc[T]`, and through them `string` and `HashMap`. The printers in
`greengold/debug/` (`gg debug-scripts`) then show `string`, `List`, `HashMap`, and `Optional` as values.
"""
from __future__ import annotations

import os
from pathlib import Path

from llvmlite import ir

from .typeinfo import array_info, heap_inner, heap_kind, is_array_type, is_ptr_type, is_slice_type, ptr_elem, slice_elem_type

_BASIC = {
    "i8": (8, "DW_ATE_signed"), "i16": (16, "DW_ATE_signed"), "i32": (32, "DW_ATE_signed"),
    "i64": (64, "DW_ATE_signed"), "i128": (128, "DW_ATE_signed"), "u128": (128, "DW_ATE_unsigned"), "isize": (64, "DW_ATE_signed"),
    "u8": (8, "DW_ATE_unsigned"), "u16": (16, "DW_ATE_unsigned"), "u32": (32, "DW_ATE_unsigned"),
    "u64": (64, "DW_ATE_unsigned"), "usize": (64, "DW_ATE_unsigned"),
    "f16": (16, "DW_ATE_float"), "f32": (32, "DW_ATE_float"), "f64": (64, "DW_ATE_float"), "bool": (8, "DW_ATE_boolean"),
}


class DebugInfo:
    def __init__(self, mod: ir.Module, primary: str, optimized: bool) -> None:
        self.mod = mod
        i32 = ir.IntType(32)
        flags = mod.add_named_metadata("llvm.module.flags")
        flags.add(mod.add_metadata([i32(2), "Dwarf Version", i32(4)]))
        flags.add(mod.add_metadata([i32(2), "Debug Info Version", i32(3)]))
        self.files: dict[str, ir.DIValue] = {}
        self.types: dict[str, ir.DIValue | None] = {}
        self.cu = mod.add_debug_info("DICompileUnit", {
            "language": ir.DIToken("DW_LANG_C"),
            "file": self.file(primary),
            "producer": "greengold",
            "runtimeVersion": 0,
            "isOptimized": optimized,
            "emissionKind": ir.DIToken("FullDebug"),
        }, is_distinct=True)
        mod.add_named_metadata("llvm.dbg.cu").add(self.cu)
        self.no_types = mod.add_debug_info("DISubroutineType", {"types": mod.add_metadata([None])})
        self._declare: ir.Function | None = None

    def file(self, path: str | None) -> ir.DIValue:
        path = path or "<source>"
        found = self.files.get(path)
        if found is None:
            p = Path(path)
            directory = str(p.parent) if p.parent != Path("") else os.getcwd()
            found = self.mod.add_debug_info("DIFile", {"filename": p.name, "directory": directory})
            self.files[path] = found
        return found

    def subprogram(self, fn: ir.Function, name: str, path: str | None, line: int) -> ir.DIValue:
        f = self.file(path)
        sp = self.mod.add_debug_info("DISubprogram", {
            "name": name, "linkageName": fn.name, "scope": f, "file": f, "line": line,
            "type": self.no_types, "scopeLine": line,
            "spFlags": ir.DIToken("DISPFlagLocalToUnit | DISPFlagDefinition"), "unit": self.cu,
        }, is_distinct=True)
        fn.set_metadata("dbg", sp)
        return sp

    def location(self, line: int, col: int, scope: ir.DIValue) -> ir.DIValue:
        return self.mod.add_debug_info("DILocation", {"line": max(line, 1), "column": max(col, 0), "scope": scope})

    def type_of(self, ty: str, cg) -> ir.DIValue | None:
        """A debug description of `ty`, or None when it is not described. `cg` is the code generator (its
        struct and enum infos and `size_align`)."""
        if ty in self.types:
            return self.types[ty]
        self.types[ty] = None  # a type that contains itself stops here (a pointer to it becomes `void*`)
        try:
            out = self._describe(ty, cg)
        except Exception:  # an unusual type is left undescribed rather than failing the build
            out = None
        self.types[ty] = out
        return out

    def _describe(self, ty: str, cg) -> ir.DIValue | None:
        structs, enums = cg.program.struct_infos, cg.program.enum_infos
        name = ty.replace("::", ".")
        if ty in _BASIC:
            bits, enc = _BASIC[ty]
            return self.mod.add_debug_info("DIBasicType", {"name": ty, "size": bits, "encoding": ir.DIToken(enc)})
        if ty == "str" or is_slice_type(ty):
            elem = "u8" if ty == "str" else slice_elem_type(ty)
            return self._struct(name, 16, [("ptr", self._pointer(elem, cg), 8, 0), ("len", self.type_of("usize", cg), 8, 8)])
        if is_ptr_type(ty):
            return self._pointer(ptr_elem(ty), cg)
        if is_array_type(ty):
            n, elem = array_info(ty)
            et = self.type_of(elem, cg)
            if et is None:
                return None
            sub = self.mod.add_debug_info("DISubrange", {"count": n})
            return self.mod.add_debug_info("DICompositeType", {
                "tag": ir.DIToken("DW_TAG_array_type"), "baseType": et, "size": cg.size_align(ty)[0] * 8,
                "elements": self.mod.add_metadata([sub]),
            })
        hk = heap_kind(ty)
        if hk == "List":
            usize = self.type_of("usize", cg)
            return self._struct(name, 24, [("ptr", self._pointer(heap_inner(ty), cg), 8, 0), ("len", usize, 8, 8),
                                           ("cap", usize, 8, 16)])
        if hk == "Box":
            return self._struct(name, 8, [("ptr", self._pointer(heap_inner(ty), cg), 8, 0)])
        if hk in ("Shared", "Arc"):
            inner = heap_inner(ty)
            isz, ial = cg.size_align(inner)
            voff = (8 + ial - 1) // ial * ial
            cell = self._struct(f"{name}.cell", voff + isz, [("count", self.type_of("u64", cg), 8, 0),
                                                              ("value", self.type_of(inner, cg), isz, voff)])
            return self._struct(name, 8, [("ptr", self._pointer_to(cell), 8, 0)])
        if ty in structs:
            info = structs[ty]
            if getattr(info.decl, "is_union", False) or getattr(info.decl, "packed", False):
                return None
            fields = []
            offset = 0
            for fname, fty in info.fields.items():
                ref = fname in info.field_modes  # a reference field holds a pointer
                size, align = (8, 8) if ref else cg.size_align(fty)
                offset = (offset + align - 1) // align * align
                fields.append((fname, self._pointer(fty, cg) if ref else self.type_of(fty, cg), size, offset))
                offset += size
            return self._struct(name, cg.size_align(ty)[0], fields)
        if ty in enums:
            return self._enum(ty, enums[ty], cg)
        return None

    def _enum(self, ty: str, info, cg) -> ir.DIValue:
        """`{tag, payload}`: the tag is an enumeration of the variant names, the payload a union with one struct
        of fields `_0`, `_1`, ... per variant that carries values."""
        name = ty.replace("::", ".")
        u32 = self.type_of("u32", cg)
        enumerators = [self.mod.add_debug_info("DIEnumerator", {"name": v, "value": i})
                       for i, v in enumerate(info.variants)]
        tag = self.mod.add_debug_info("DICompositeType", {
            "tag": ir.DIToken("DW_TAG_enumeration_type"), "name": f"{name}.Tag", "size": 32, "baseType": u32,
            "elements": self.mod.add_metadata(enumerators),
        })
        size = cg.size_align(ty)[0]
        words = size - 8
        fields = [("tag", tag, 4, 0)]
        if words > 0:
            arms = []
            for vname, v in info.variants.items():
                if not v.payload:
                    continue
                parts, off, al = [], 0, 1
                for i, pty in enumerate(v.payload):
                    s, a = cg.size_align(pty)
                    off = (off + a - 1) // a * a
                    parts.append((f"_{i}", self.type_of(pty, cg), s, off))
                    off += s
                    al = max(al, a)
                vsize = (off + al - 1) // al * al
                arms.append(self._member(vname, self._struct(f"{name}.{vname}", vsize, parts), vsize, 0))
            members = arms
            union = self.mod.add_debug_info("DICompositeType", {
                "tag": ir.DIToken("DW_TAG_union_type"), "name": f"{name}.Payload", "size": words * 8,
                "elements": self.mod.add_metadata(members),
            })
            fields.append(("payload", union, words, 8))
        return self._struct(name, size, fields)

    def _pointer(self, elem: str, cg) -> ir.DIValue:
        return self._pointer_to(None if elem == "void" else self.type_of(elem, cg))

    def _pointer_to(self, base: ir.DIValue | None) -> ir.DIValue:
        return self.mod.add_debug_info("DIDerivedType", {"tag": ir.DIToken("DW_TAG_pointer_type"), "baseType": base,
                                                          "size": 64})

    def _member(self, name: str, t: ir.DIValue, size: int, offset: int) -> ir.DIValue:
        return self.mod.add_debug_info("DIDerivedType", {
            "tag": ir.DIToken("DW_TAG_member"), "name": name, "baseType": t, "size": size * 8, "offset": offset * 8,
        })

    def _struct(self, name: str, size: int, fields: list) -> ir.DIValue:
        members = [self._member(n, t, s, o) for n, t, s, o in fields if t is not None]
        return self.mod.add_debug_info("DICompositeType", {
            "tag": ir.DIToken("DW_TAG_structure_type"), "name": name, "size": size * 8,
            "elements": self.mod.add_metadata(members),
        })

    def declare(self, b: ir.IRBuilder, slot: ir.Value, name: str, ditype: ir.DIValue, scope: ir.DIValue,
                path: str | None, line: int, loc: ir.DIValue) -> None:
        if self._declare is None:
            md = ir.MetaDataType()
            self._declare = ir.Function(self.mod, ir.FunctionType(ir.VoidType(), [md, md, md]), "llvm.dbg.declare")
        var = self.mod.add_debug_info("DILocalVariable", {
            "name": name, "scope": scope, "file": self.file(path), "line": max(line, 1), "type": ditype,
        })
        expr = self.mod.add_debug_info("DIExpression", {})
        call = b.call(self._declare, [slot, var, expr])
        call.set_metadata("dbg", loc)
