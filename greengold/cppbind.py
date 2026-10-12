"""`gg bindgen --cpp header.hpp`: use a C++ library from Greengold.

C++ has no stable binary interface, so the binding has two halves:

* `<name>_shim.cpp`: `extern "C"` functions that call the C++ code (`new`, `delete`, methods, functions).
  List it under `[native] sources` in gg.toml; it is compiled with the package.
* `<name>.gg`: a Greengold module. Each C++ class becomes a struct that owns one C++ object: `Type.new(...)`
  constructs it, methods call through the shim, and `drop` deletes the object. Free functions become
  functions. `const` methods take `self: read Self`, others `self: lend Self`.

Supported in signatures: integers, `float`, `double`, `bool`, `size_t` and the `<cstdint>` types, `void`,
`const char*` and `std::string` (passed as `str`, returned as `string`), and classes of the header by
pointer or reference. Namespaces are followed. Templates, overloads after the first, operators, and other
types are written as `# skipped:` comments.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .bindgen import _strip_comments

_INTS = {
    "int": "i32", "unsigned": "u32", "unsigned int": "u32", "short": "i16", "unsigned short": "u16",
    "long long": "i64", "unsigned long long": "u64", "char": "u8", "unsigned char": "u8", "signed char": "i8",
    "int8_t": "i8", "int16_t": "i16", "int32_t": "i32", "int64_t": "i64",
    "uint8_t": "u8", "uint16_t": "u16", "uint32_t": "u32", "uint64_t": "u64",
    "std::int32_t": "i32", "std::int64_t": "i64", "std::uint32_t": "u32", "std::uint64_t": "u64",
    "size_t": "usize", "std::size_t": "usize", "float": "f32", "double": "f64", "bool": "bool",
}
_STRINGS = {"const char*", "std::string", "const std::string&", "std::string_view", "const std::string_view&"}
_KEYWORDS = {"read", "lend", "consume", "fn", "match", "type", "test", "self", "string", "str", "print", "drop",
             "new", "fixed", "var", "in", "elif", "and", "or", "not", "pass", "require", "send"}


@dataclass
class _Fn:
    name: str
    ret: str
    params: list[tuple[str, str]]  # (C++ type, name)
    const: bool = False


@dataclass
class _Class:
    name: str        # Greengold name
    cpp: str         # qualified C++ name
    ctors: list[_Fn] = field(default_factory=list)
    methods: list[_Fn] = field(default_factory=list)


class _Skip(Exception):
    pass


def _norm(t: str) -> str:
    t = re.sub(r"\s+", " ", t.strip())
    t = re.sub(r"\s*([*&])\s*", r"\1", t)
    return t.replace("const ", "const ").strip()


def _split_params(text: str) -> list[tuple[str, str]]:
    text = text.strip()
    if text in ("", "void"):
        return []
    out = []
    for i, part in enumerate(p.strip() for p in text.split(",")):
        part = part.split("=")[0].strip()  # default values are dropped
        m = re.match(r"^(.*?)([A-Za-z_]\w*)$", part)
        if m and m.group(1).strip() and not m.group(1).strip().endswith("::"):
            ty, name = m.group(1), m.group(2)
        else:
            ty, name = part, f"a{i}"
        out.append((_norm(ty), name))
    return out


class CppBinder:
    def __init__(self, text: str) -> None:
        self.text = _strip_comments(text)
        self.classes: dict[str, _Class] = {}
        self.funcs: list[tuple[str, _Fn]] = []  # (qualified C++ name, function)
        self.skipped: list[str] = []

    # -- parsing a header ---------------------------------------------------------------------
    def parse(self) -> None:
        text = re.sub(r"^\s*#.*$", "", self.text, flags=re.M)
        self._scope(text, [])

    def _scope(self, text: str, ns: list[str]) -> None:
        i = 0
        while i < len(text):
            m = re.compile(r"\b(namespace)\s+(\w+)\s*\{|\b(class|struct)\s+(\w+)\s*(?::[^{;]*)?\{|template\s*<").search(text, i)
            head = text[i:m.start()] if m else text[i:]
            self._functions(head, ns)
            if not m:
                return
            if m.group(0).startswith("template"):
                end = self._skip_decl(text, m.end())
                self.skipped.append("template: " + " ".join(text[m.start():end].split())[:80])
                i = end
                continue
            body_start = m.end()
            body_end = self._match_brace(text, body_start - 1)
            body = text[body_start:body_end]
            if m.group(1):
                self._scope(body, ns + [m.group(2)])
            else:
                self._class(m.group(3), m.group(4), body, ns)
            i = body_end + 1
            if i < len(text) and text[i] == ";":
                i += 1

    @staticmethod
    def _match_brace(text: str, open_at: int) -> int:
        depth = 0
        for k in range(open_at, len(text)):
            if text[k] == "{":
                depth += 1
            elif text[k] == "}":
                depth -= 1
                if depth == 0:
                    return k
        return len(text)

    def _skip_decl(self, text: str, at: int) -> int:
        k = at
        while k < len(text) and text[k] not in ";{":
            k += 1
        if k < len(text) and text[k] == "{":
            k = self._match_brace(text, k) + 1
        return k + 1

    def _class(self, kind: str, name: str, body: str, ns: list[str]) -> None:
        cls = _Class(name, "::".join(ns + [name]))
        public = kind == "struct"
        flat = re.sub(r"\{[^{}]*\}", ";", body)  # inline bodies become plain declarations
        for part in re.split(r"(public\s*:|private\s*:|protected\s*:|;)", flat):
            part = part.strip()
            if not part or part == ";":
                continue
            if re.fullmatch(r"public\s*:", part):
                public = True
                continue
            if re.fullmatch(r"(private|protected)\s*:", part):
                public = False
                continue
            if not public or "(" not in part:
                continue
            decl = " ".join(part.split())
            decl = re.sub(r"\)\s*:(?!:).*$", ")", decl)  # a constructor's member initializers
            decl = re.sub(r"\b(virtual|explicit|inline|static|override|final|noexcept)\b", "", decl).strip()
            if decl.startswith("~") or "operator" in decl or "= delete" in decl:
                continue
            m = re.match(r"^(?:(.*?)\s+)?(\w+)\s*\((.*)\)\s*(const)?\s*(?=\s*0)?\s*$", decl)
            if not m:
                self.skipped.append(f"{name}: {decl[:80]}")
                continue
            ret, fname, params, const = m.group(1), m.group(2), m.group(3), bool(m.group(4))
            fn = _Fn(fname, _norm(ret or ""), _split_params(params), const)
            if fname == name and not ret:
                if cls.ctors:
                    self.skipped.append(f"{name}: constructor overload {decl[:60]}")
                else:
                    cls.ctors.append(fn)
            elif any(x.name == fname for x in cls.methods):
                self.skipped.append(f"{name}: overload {decl[:60]}")
            else:
                cls.methods.append(fn)
        self.classes[name] = cls

    def _functions(self, text: str, ns: list[str]) -> None:
        while re.search(r"\{[^{}]*\}", text):  # function bodies become plain declarations
            text = re.sub(r"\{[^{}]*\}", ";", text)
        for decl in text.split(";"):
            decl = " ".join(decl.split())
            decl = re.sub(r"\b(inline|static|extern \"C\"|extern|noexcept)\b", "", decl).strip()
            if "(" not in decl or decl.startswith("using") or decl.startswith("typedef"):
                continue
            m = re.match(r"^(.*?)\s*\b(\w+)\s*\((.*)\)\s*$", decl)
            if not m or not m.group(1):
                continue
            q = "::".join(ns + [m.group(2)])
            if any(n == q for n, _ in self.funcs):
                self.skipped.append(f"overload {q}")
                continue
            self.funcs.append((q, _Fn(m.group(2), _norm(m.group(1)), _split_params(m.group(3)))))

    # -- types --------------------------------------------------------------------------------
    def _class_of(self, t: str) -> str | None:
        base = t.replace("const ", "").rstrip("*&").split("::")[-1]
        return base if base in self.classes and t.replace("const ", "").endswith(("*", "&")) else None

    def gg_param(self, t: str) -> str:
        if t in _INTS:
            return _INTS[t]
        if t in _STRINGS:
            return "str"
        if self._class_of(t):
            return "*mut u8"
        raise _Skip(f"type `{t}`")

    def c_param(self, t: str) -> str:
        if t in _INTS:
            return t
        if t in _STRINGS:
            return "const char*"
        if self._class_of(t):
            return "void*"
        raise _Skip(f"type `{t}`")

    def ret_kind(self, t: str) -> str:
        if t in ("", "void"):
            return "void"
        if t in _INTS:
            return "int"
        if t in ("std::string", "const std::string&", "const char*"):
            return "string"
        raise _Skip(f"result type `{t}`")

    def arg_expr(self, t: str, name: str) -> str:
        cls = self._class_of(t)
        if cls:
            q = self.classes[cls].cpp
            return f"*static_cast<{q}*>({name})" if t.endswith("&") else f"static_cast<{q}*>({name})"
        return name

    # -- output -------------------------------------------------------------------------------
    def shim(self, header: str) -> str:
        out = [f'// Generated by `gg bindgen --cpp`: C entry points for {header}.', f'#include "{header}"',
               "#include <cstdlib>", "#include <cstring>", "#include <string>", "", 'extern "C" {', "",
               "static char* gg_copy(const std::string& s) {",
               "    char* p = static_cast<char*>(std::malloc(s.size() + 1));",
               "    std::memcpy(p, s.c_str(), s.size() + 1);",
               "    return p;", "}", ""]
        for cls in self.classes.values():
            for ctor in cls.ctors[:1]:
                try:
                    ps = ", ".join(f"{self.c_param(t)} {n}" for t, n in ctor.params)
                    args = ", ".join(self.arg_expr(t, n) for t, n in ctor.params)
                except _Skip:
                    continue
                out.append(f"void* gg_{cls.name}_new({ps}) {{ return new {cls.cpp}({args}); }}")
            out.append(f"void gg_{cls.name}_delete(void* self) {{ delete static_cast<{cls.cpp}*>(self); }}")
            for m in cls.methods:
                line = self._shim_fn(f"gg_{cls.name}_{m.name}", m, f"static_cast<{cls.cpp}*>(self)->{m.name}",
                                     ["void* self"])
                if line:
                    out.append(line)
            out.append("")
        for q, f in self.funcs:
            line = self._shim_fn(f"gg_fn_{q.replace('::', '_')}", f, q, [])
            if line:
                out.append(line)
        out += ["", "}  // extern \"C\"", ""]
        return "\n".join(out)

    def _shim_fn(self, cname: str, f: _Fn, call: str, first: list[str]) -> str | None:
        try:
            ps = first + [f"{self.c_param(t)} {n}" for t, n in f.params]
            args = ", ".join(self.arg_expr(t, n) for t, n in f.params)
            kind = self.ret_kind(f.ret)
        except _Skip as why:
            self.skipped.append(f"{call.split('->')[-1]}: {why}")
            return None
        if kind == "void":
            return f"void {cname}({', '.join(ps)}) {{ {call}({args}); }}"
        if kind == "string":
            return f"char* {cname}({', '.join(ps)}) {{ return gg_copy({call}({args})); }}"
        return f"{f.ret} {cname}({', '.join(ps)}) {{ return {call}({args}); }}"

    def module(self, header: str, shim_name: str) -> str:
        externs: list[str] = []
        body: list[str] = []
        for cls in self.classes.values():
            body += [f"# The C++ class `{cls.cpp}`; the object is deleted when this value goes away.",
                     f"struct {cls.name}:", "    private", "    handle: *mut u8", "", "public", f"impl {cls.name}:"]
            for ctor in cls.ctors[:1]:
                try:
                    gp = ", ".join(f"{_safe(n)}: {self.gg_param(t)}" for t, n in ctor.params)
                    cp = ", ".join(f"{_safe(n)}: {self.gg_param(t)}" for t, n in ctor.params)
                except _Skip:
                    continue
                externs.append(f'extern "{shim_name}" fn gg_{cls.name}_new({cp}) -> *mut u8')
                args = ", ".join(self._gg_arg(t, _safe(n)) for t, n in ctor.params)
                body += [f"    fn new({gp}) -> {cls.name}:", "        unsafe:",
                         f"            return {cls.name}{{ handle: gg_{cls.name}_new({args}) }}", ""]
            externs.append(f'extern "{shim_name}" fn gg_{cls.name}_delete(p: *mut u8)')
            for m in cls.methods:
                sig = self._gg_fn(f"gg_{cls.name}_{m.name}", m, shim_name, externs, method=True)
                if sig is None:
                    continue
                params, ret, call, kind = sig
                mode = "read" if m.const else "lend"
                body += [f"    fn {_safe(m.name)}(self: {mode} Self{params}){ret}:"] + self._gg_body(call, kind, 8) + [""]
            body += ["    fn drop(self: lend Self):", "        unsafe:", f"            gg_{cls.name}_delete(self.handle)", ""]
        for q, f in self.funcs:
            sig = self._gg_fn(f"gg_fn_{q.replace('::', '_')}", f, shim_name, externs, method=False)
            if sig is None:
                continue
            params, ret, call, kind = sig
            body += [f"fn {_safe(f.name)}({params.lstrip(', ')}){ret}:"] + self._gg_body(call, kind, 4) + [""]
        head = [f"# Generated by `gg bindgen --cpp` from {header}. Compile `{shim_name}` with the package:",
                f'#   [native] sources = ["{shim_name}"]', "", "private",
                'extern "stdlib.h" fn free(p: *u8)'] + externs + ["", "public"]
        tail = [f"# skipped: {s}" for s in self.skipped]
        return "\n".join(head + body + tail).rstrip() + "\n"

    def _gg_arg(self, t: str, name: str) -> str:
        cls = self._class_of(t)
        return f"{name}.handle" if cls else name

    def _gg_fn(self, cname: str, f: _Fn, shim: str, externs: list[str], method: bool):
        try:
            gps = []
            cps = ["self: *mut u8"] if method else []
            args = ["self.handle"] if method else []
            for t, n in f.params:
                cls = self._class_of(t)
                gps.append(f"{_safe(n)}: {'read ' + cls if cls else self.gg_param(t)}")
                cps.append(f"{_safe(n)}: {self.gg_param(t)}")
                args.append(self._gg_arg(t, _safe(n)))
            kind = self.ret_kind(f.ret)
        except _Skip as why:
            if not any(f.name in s for s in self.skipped):
                self.skipped.append(f"{f.name}: {why}")
            return None
        cret = {"void": "", "string": " -> *mut u8"}.get(kind, f" -> {_INTS.get(f.ret, 'i32')}")
        externs.append(f'extern "{shim}" fn {cname}({", ".join(cps)}){cret}')
        ret = {"void": "", "string": " -> string"}.get(kind, f" -> {_INTS.get(f.ret, 'i32')}")
        params = "".join(f", {p}" for p in gps)
        return params, ret, f"{cname}({', '.join(args)})", kind

    @staticmethod
    def _gg_body(call: str, kind: str, indent: int) -> list[str]:
        pad = " " * indent
        if kind == "string":
            return [f"{pad}unsafe:", f"{pad}    p = {call}", f"{pad}    s = cstr_to_string(p).to_string()",
                    f"{pad}    free(p)", f"{pad}    return s"]
        if kind == "void":
            return [f"{pad}unsafe:", f"{pad}    {call}"]
        return [f"{pad}unsafe:", f"{pad}    return {call}"]


def _safe(name: str) -> str:
    return name + "_" if name in _KEYWORDS else name


def cpp_bindgen(text: str, header: str, stem: str) -> tuple[str, str]:
    """(Greengold module, C++ shim) for the C++ header `text`."""
    b = CppBinder(text)
    b.parse()
    shim_name = f"{stem}_shim.cpp"
    shim = b.shim(header)
    return b.module(header, shim_name), shim
