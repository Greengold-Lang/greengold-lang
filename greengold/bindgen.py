"""`gg bindgen`: generates Greengold `extern` declarations from a C header file.

Dependency-free and deliberately simple: strips comments/preprocessor lines, reads `#define NAME <int>` constants,
`enum` constants and types (`enum Color: RED = 0`), `struct` definitions (`extern struct`), `union`s, function
pointers (`fn(i32) -> i32`, in typedefs, parameters, and fields), bitfields (packed into an integer field with a
comment showing the bits), and function prototypes (`extern fn`). Structs are passed by value as C does.
Instead of silently dropping what it cannot translate (macro functions, anonymous nested types, `long double`
...), it writes them to output as `# skipped: ...` comments.

Type mappings: `T *` -> `*mut T`, `const T *` -> `*T`, `void *` -> `*mut void`, `char` -> `u8`, `int` -> `i32`,
`size_t` -> `usize`, `long` -> platform-dependent (`i32` on Windows, `i64` otherwise).
"""
from __future__ import annotations

import re
import sys

from .lexer import KEYWORDS
from .typeinfo import BUILTINS, PRELUDE_NAMES, PRIMS

STD_TYPES = {
    "int8_t": "i8", "int16_t": "i16", "int32_t": "i32", "int64_t": "i64",
    "uint8_t": "u8", "uint16_t": "u16", "uint32_t": "u32", "uint64_t": "u64",
    "size_t": "usize", "ssize_t": "isize", "ptrdiff_t": "isize", "intptr_t": "isize", "uintptr_t": "usize",
    "off_t": "i64", "time_t": "i64", "bool": "bool", "_Bool": "bool",
}
PRIM_WORDS = {"unsigned", "signed", "long", "short", "int", "char", "float", "double", "void", "_Bool"}
QUALIFIERS = {"volatile", "restrict", "__restrict", "__restrict__", "inline", "__inline", "__inline__", "static",
              "extern", "register", "_Noreturn", "__extension__"}
RESERVED_NAMES = set(KEYWORDS) | BUILTINS | PRELUDE_NAMES | PRIMS | {"string", "self", "ref", "main"}
TOKEN_RE = re.compile(r"\.\.\.|[A-Za-z_]\w*|0[xX][0-9a-fA-F]+|\d+|[*()\[\],:;{}=+\-<>|&^~!/%.]")


class Unsupported(Exception):
    """This declaration cannot be translated to Greengold (reason in message)."""


def _strip_comments(text: str) -> str:
    out: list[str] = []
    i, n = 0, len(text)
    while i < n:
        two = text[i:i + 2]
        if two == "/*":
            j = text.find("*/", i + 2)
            i = n if j < 0 else j + 2
            out.append(" ")
        elif two == "//":
            j = text.find("\n", i)
            i = n if j < 0 else j
        elif text[i] == '"':  # string literal (e.g. `extern "C"`) remains as is
            j = i + 1
            while j < n and text[j] != '"':
                j += 2 if text[j] == "\\" else 1
            out.append(text[i:j + 1])
            i = j + 1
        else:
            out.append(text[i])
            i += 1
    return "".join(out)


def _parse_int(tok: str) -> int | None:
    tok = tok.strip().rstrip("uUlL")
    try:
        return int(tok, 0)
    except ValueError:
        return None


class _Struct:
    def __init__(self, name: str) -> None:
        self.name = name
        self.fields: list[tuple[str, str]] | None = None  # None: forward declaration only (opaque)
        self.skip_reason: str | None = None
        self.is_union = False
        self.comments: dict[str, str] = {}  # field -> comment (bitfields)


class Binder:
    def __init__(self, header_name: str | None = None) -> None:
        self.header = header_name
        self.defines: dict[str, int] = {}
        self.consts: list[tuple[str, int]] = []
        self.typedefs: dict[str, str] = {}  # C name -> Greengold type (pointer if starting with "*")
        self.structs: dict[str, _Struct] = {}  # canonical name -> info
        self.struct_alias: dict[str, str] = {}  # typedef name / tag -> canonical name
        self.struct_order: list[str] = []
        self.funcs: list[str] = []
        self.notes: list[str] = []
        self.enums: list[tuple[str, list[tuple[str, int]]]] = []  # named C enums -> Greengold `enum` types

    # -- preprocessing ------------------------------------------------------------------
    def preprocess(self, text: str) -> str:
        text = _strip_comments(text)
        text = re.sub(r"\\\s*\n", " ", text)
        lines: list[str] = []
        for line in text.split("\n"):
            s = line.strip()
            if s.startswith("#"):
                m = re.match(r"#\s*define\s+(\w+)\s+(\(?-?\s*(?:0[xX][0-9a-fA-F]+|\d+)[uUlL]*\)?)\s*$", s)
                if m:
                    val = _parse_int(m.group(2).strip("() ").replace(" ", ""))
                    if val is not None:
                        self.defines[m.group(1)] = val
                        self.consts.append((m.group(1), val))
                elif re.match(r"#\s*define\s+\w+\(", s):
                    self.notes.append(f"function-like macro: {s[:60]}")
                continue
            lines.append(line)
        return "\n".join(lines)

    # -- top-level declaration splitting -----------------------------------------------------
    def split_decls(self, text: str) -> list[str]:
        decls: list[str] = []
        cur: list[str] = []
        depth = 0
        wrapped = 0  # `extern "C" {` wrappers
        i, n = 0, len(text)
        while i < n:
            ch = text[i]
            if depth == 0 and not "".join(cur).strip():
                m = re.match(r'\s*extern\s*"C"\s*\{', text[i:])
                if m:
                    wrapped += 1
                    i += m.end()
                    cur = []
                    continue
            if ch == "{":
                depth += 1
                cur.append(ch)
            elif ch == "}":
                if depth == 0 and wrapped:
                    wrapped -= 1
                    i += 1
                    continue
                depth -= 1
                cur.append(ch)
                if depth == 0:
                    head = "".join(cur)
                    first = head.strip().split("{", 1)[0]
                    is_func_body = "(" in first and not re.match(r"\s*(typedef|struct|union|enum)\b", first)
                    if is_func_body:  # `static inline int f(...) { ... }`: definition with body is skipped
                        decls.append(head.strip() + ";")
                        cur = []
            elif ch == ";" and depth == 0:
                s = "".join(cur).strip()
                if s:
                    decls.append(s)
                cur = []
            else:
                cur.append(ch)
            i += 1
        rest = "".join(cur).strip()
        if rest:
            decls.append(rest)
        return decls

    # -- type resolution -----------------------------------------------------------------
    def _struct_name(self, tag: str) -> str:
        return self.struct_alias.get(tag, tag)

    def resolve_base(self, words: list[str]) -> str:
        """Translates base type words (`unsigned long`, `struct Node`, `Vec2` ...) to Greengold type."""
        if not words:
            raise Unsupported("no type")
        if words[0] in ("struct", "union", "enum"):
            kind, tag = words[0], words[1]
            if kind == "enum":
                return "i32"
            return "@struct:" + self._struct_name(tag)
        if len(words) == 1 and words[0] in self.typedefs:
            if self.typedefs[words[0]] == "@unsupported":
                raise Unsupported(f"`{words[0]}` is a type that could not be translated")
            return self.typedefs[words[0]]
        if len(words) == 1 and words[0] in self.struct_alias:
            return "@struct:" + self.struct_alias[words[0]]
        if len(words) == 1 and words[0] in STD_TYPES:
            return STD_TYPES[words[0]]
        ws = list(words)
        unsigned, signed, short = "unsigned" in ws, "signed" in ws, "short" in ws
        longs = ws.count("long")
        core = [w for w in ws if w not in ("unsigned", "signed", "long", "short", "int")]
        if core == ["char"]:
            return "i8" if signed else "u8"
        if core == ["float"]:
            return "f32"
        if core == ["double"]:
            if longs:
                raise Unsupported("long double")
            return "f64"
        if core == ["void"]:
            return "void"
        if core == ["_Bool"]:
            return "bool"
        if not core:
            if short:
                bits = 16
            elif longs >= 2:
                bits = 64
            elif longs == 1:
                bits = 32 if sys.platform == "win32" else 64
            else:
                bits = 32
            return f"{'u' if unsigned else 'i'}{bits}"
        raise Unsupported(f"unknown type `{' '.join(words)}`")

    def finish(self, ty: str, pointee: bool = False) -> str:
        """Resolves `@struct:Name` placeholder to real name (or `void` if opaque)."""
        if ty.startswith("@struct:"):
            name = ty[8:]
            st = self.structs.get(name)
            if st is None or st.fields is None:
                if pointee:
                    return "void"  # opaque struct: can only be used as a pointer
                raise Unsupported(f"`{name}` is an opaque/unknown struct (cannot be used by value)")
            if st.skip_reason:
                raise Unsupported(f"struct `{name}` skipped: {st.skip_reason}")
            return name
        return ty

    def apply_stars(self, base: str, stars: list[bool]) -> str:
        """`stars`: whether pointed-to target is `const` for each `*`. `base` can be a placeholder."""
        ty = base
        for idx, is_const in enumerate(stars):
            inner = self.finish(ty, pointee=True) if idx == 0 else ty
            ty = f"*{inner}" if is_const else f"*mut {inner}"
        if not stars:
            ty = self.finish(ty)
        return ty

    # -- declarator parsing ------------------------------------------------------------
    def parse_declarator(self, toks: list[str]) -> tuple[str, str | None, list[str]]:
        """`const char *name[4]` -> (base type text, name, remaining array/paren tokens). Pointers applied."""
        i, n = 0, len(toks)
        base: list[str] = []
        base_const = False
        while i < n:
            t = toks[i]
            if t == "const":
                base_const = True
                i += 1
            elif t in QUALIFIERS or t.startswith("__attribute__") or t.startswith("__declspec"):
                i += 1
            elif t in ("struct", "union", "enum"):
                if i + 1 >= n:
                    raise Unsupported("missing struct name")
                base += [t, toks[i + 1]]
                i += 2
            elif t in PRIM_WORDS:
                base.append(t)
                i += 1
            elif not base and re.match(r"[A-Za-z_]\w*$", t):
                base.append(t)
                i += 1
            else:
                break
        stars: list[bool] = []
        pending_const = base_const
        while i < n and toks[i] in ("*", "const", "volatile", "restrict", "__restrict"):
            if toks[i] == "*":
                stars.append(pending_const)
                pending_const = False
            elif toks[i] == "const":
                pending_const = True
            i += 1
        name = None
        if i < n and re.match(r"[A-Za-z_]\w*$", toks[i]) and toks[i] not in ("const",):
            name = toks[i]
            i += 1
        rest = toks[i:]
        ty = self.apply_stars(self.resolve_base(base), stars)
        return ty, name, rest

    def array_dims(self, rest: list[str]) -> list[int | None]:
        dims: list[int | None] = []
        i = 0
        while i < len(rest) and rest[i] == "[":
            j = i + 1
            inner: list[str] = []
            while j < len(rest) and rest[j] != "]":
                inner.append(rest[j])
                j += 1
            if not inner:
                dims.append(None)
            elif len(inner) == 1 and _parse_int(inner[0]) is not None:
                dims.append(_parse_int(inner[0]))
            elif len(inner) == 1 and inner[0] in self.defines:
                dims.append(self.defines[inner[0]])
            else:
                raise Unsupported(f"could not resolve array size `{' '.join(inner)}`")
            i = j + 1
        return dims

    # -- declaration kinds -------------------------------------------------------------------
    def handle(self, decl: str) -> None:
        d = decl.strip()
        if not d:
            return
        try:
            if re.match(r"typedef\b", d):
                self.handle_typedef(d[len("typedef"):].strip())
            elif re.match(r"(struct|union)\s+\w*\s*\{", d):
                self.handle_struct_def(d, None)
            elif re.match(r"enum\s*\w*\s*\{", d):
                self.handle_enum_def(d)
            elif re.match(r"(struct|union|enum)\s+\w+$", d):
                tag = d.split()[1]
                if d.startswith(("struct", "union")):
                    self.declare_struct(tag)
            elif "(" in d.split("{", 1)[0]:
                self.handle_function(d)
            elif "{" in d:
                raise Unsupported("unrecognized block")
            else:
                self.notes.append(f"global variable: {d[:60]}")
        except Unsupported as err:
            self.notes.append(f"{' '.join(d.split())[:70]}  ({err})")

    def declare_struct(self, tag: str) -> _Struct:
        name = self._struct_name(tag)
        st = self.structs.get(name)
        if st is None:
            st = _Struct(name)
            self.structs[name] = st
            self.struct_alias.setdefault(tag, name)
        return st

    def handle_typedef(self, body: str) -> None:
        m = re.match(r"(struct|union)\s*(\w*)\s*\{", body)
        if m:  # typedef struct Tag { ... } Alias;
            end = body.rindex("}")
            alias = body[end + 1:].strip().split(",")[0].strip()
            self.handle_struct_def(body[:end + 1], alias or None)
            return
        if re.match(r"enum\s*\w*\s*\{", body):
            end = body.rindex("}")
            alias = body[end + 1:].strip()
            self.handle_enum_def(body[:end + 1], alias or None)
            if alias:
                self.typedefs[alias] = "i32"
            return
        toks = TOKEN_RE.findall(body)
        if "(" in toks:  # `typedef int (*cmp_fn)(const void *, const void *);`
            name, fty = self.parse_fn_pointer(toks)
            self.typedefs[name] = fty
            return
        # `typedef struct Node Node;`: ileri bildirim
        if len(toks) == 3 and toks[0] == "struct" and toks[1] == toks[2]:
            self.declare_struct(toks[1])
            return
        if len(toks) == 3 and toks[0] == "struct":
            st = self.declare_struct(toks[1])
            self.struct_alias[toks[2]] = st.name
            return
        ty, name, rest = self.parse_declarator(toks)
        if name is None:
            raise Unsupported("missing typedef name")
        dims = self.array_dims(rest)
        if dims:
            raise Unsupported("array typedef")
        if ty.startswith("@struct:"):
            self.struct_alias[name] = ty[8:]
        else:
            self.typedefs[name] = ty

    def handle_struct_def(self, body: str, alias: str | None) -> None:
        m = re.match(r"(struct|union)\s*(\w*)\s*\{(.*)\}\s*(\w*)\s*$", body, re.S)
        if not m:
            raise Unsupported("failed to parse struct definition")
        kind, tag, inner, trailing = m.group(1), m.group(2), m.group(3), m.group(4)
        name = tag or alias or trailing
        if not name:
            raise Unsupported(f"anonymous {kind}")
        st = self.declare_struct(name)
        st.is_union = kind == "union"
        if alias and alias != name:
            self.struct_alias[alias] = st.name
        if tag and tag != name:
            self.struct_alias[tag] = st.name
        st.fields = []
        if st.name not in self.struct_order:
            self.struct_order.append(st.name)
        bits: list[tuple[str, str, int]] = []  # pending bitfields: (name, base type, width)
        for fdecl in [f.strip() for f in inner.split(";") if f.strip()] + [None]:
            if fdecl is not None and re.match(r"[^:()]*\b\w+\s*:\s*\w+$", fdecl):  # `unsigned flags : 3`
                left, width = fdecl.rsplit(":", 1)
                try:
                    ty, fname, _rest = self.parse_declarator(TOKEN_RE.findall(left))
                    w = _parse_int(width) if _parse_int(width) is not None else self.defines.get(width.strip())
                    if fname is None or w is None or ty not in ("i8", "u8", "i16", "u16", "i32", "u32", "i64", "u64", "bool"):
                        raise Unsupported("bitfield")
                    bits.append((fname, ty, w))
                except Unsupported as err:
                    st.skip_reason = str(err)
                continue
            if bits:
                self._pack_bits(st, bits)
                bits = []
            if fdecl is None:
                break
            try:
                st.fields += self.parse_fields(fdecl, st.name)
            except Unsupported as err:
                st.skip_reason = str(err)
                self.notes.append(f"struct {st.name}: skipped field `{' '.join(fdecl.split())[:50]}` ({err})")

    def _pack_bits(self, st: _Struct, bits: list[tuple[str, str, int]]) -> None:
        """Consecutive bitfields share integers of their declared type, filled from the low bit, as GCC,
        Clang, and MSVC do when the declared types are the same. Each integer becomes one field."""
        size = {"i8": 8, "u8": 8, "bool": 8, "i16": 16, "u16": 16, "i32": 32, "u32": 32, "i64": 64, "u64": 64}
        unit: list[tuple[str, int, int]] = []
        unit_ty, used, count = None, 0, 0

        def flush() -> None:
            nonlocal unit, used, count
            if unit:
                fname = f"bits{count}" if count else "bits"
                ty = "u" + str(size[unit_ty or "u32"])
                st.fields.append((fname, ty))  # type: ignore[union-attr]
                st.comments[fname] = ", ".join(f"{n}: bits {lo}..{lo + w - 1}" for n, lo, w in unit)
                count += 1
            unit, used = [], 0

        for name, ty, w in bits:
            if unit_ty is not None and (size[ty] != size[unit_ty] or used + w > size[ty]):
                flush()
            unit_ty = ty
            if w == 0:  # `int : 0` closes the integer
                flush()
                continue
            unit.append((name, used, w))
            used += w
        flush()

    def parse_fields(self, fdecl: str, struct_name: str) -> list[tuple[str, str]]:
        toks = TOKEN_RE.findall(fdecl)
        if "(" in toks and "{" not in toks:  # `void (*on_event)(int code);`
            name, fty = self.parse_fn_pointer(toks)
            return [(self.safe_name(name), fty)]
        if "(" in toks or ":" in toks or "{" in toks:
            raise Unsupported("nested type")
        # `type a, b[2], *c`: first declarator gives base; subsequent ones use same base
        groups: list[list[str]] = [[]]
        for t in toks:
            if t == ",":
                groups.append([])
            else:
                groups[-1].append(t)
        first_ty, first_name, first_rest = self.parse_declarator(groups[0])
        base_toks = groups[0][:len(groups[0]) - len(first_rest)]
        # find base (without stars and name)
        base_only: list[str] = []
        for t in base_toks:
            if t in ("*", first_name):
                break
            base_only.append(t)
        out: list[tuple[str, str]] = []
        entries = [(first_ty, first_name, first_rest)]
        for g in groups[1:]:
            entries.append(self.parse_declarator(base_only + g))
        for ty, name, rest in entries:
            if name is None:
                raise Unsupported("missing field name")
            for dim in reversed(self.array_dims(rest)):
                if dim is None:
                    raise Unsupported("flexible array member")
                ty = f"[{dim}]{ty}"
            out.append((self.safe_name(name), ty))
        return out

    def handle_enum_def(self, body: str, alias: str | None = None) -> None:
        m = re.match(r"enum\s*(\w*)\s*\{(.*)\}", body, re.S)
        if not m:
            raise Unsupported("failed to parse enum")
        ename = m.group(1) or alias
        nxt = 0
        members: list[tuple[str, int]] = []
        for item in [x.strip() for x in m.group(2).split(",") if x.strip()]:
            if "=" in item:
                name, val = [s.strip() for s in item.split("=", 1)]
                parsed = _parse_int(val) if _parse_int(val) is not None else self.defines.get(val)
                if parsed is None:
                    self.notes.append(f"enum constant `{name}`: value `{val}` could not be evaluated")
                    return
                nxt = parsed
            else:
                name = item
            self.defines[name] = nxt
            self.consts.append((name, nxt))
            members.append((name, nxt))
            nxt += 1
        values = [v for _, v in members]
        if ename and members and len(set(values)) == len(values) and ename not in RESERVED_NAMES:
            self.enums.append((ename, members))  # a Greengold enum too: `i32(Color.RED)`, `Color.from_int(n)`

    def safe_name(self, name: str) -> str:
        return name + "_" if name in RESERVED_NAMES else name

    def handle_function(self, d: str) -> None:
        d = re.sub(r"__attribute__\s*\(\(.*?\)\)", " ", d)
        d = re.sub(r"__declspec\s*\(.*?\)", " ", d)
        d = re.sub(r"\b(__cdecl|__stdcall|WINAPI|CALLBACK)\b", " ", d)
        if "{" in d:  # inline definition with body
            raise Unsupported("function definition with body")
        open_i = d.index("(")
        close_i = d.rindex(")")
        head, params_txt = d[:open_i], d[open_i + 1:close_i]
        head_toks = TOKEN_RE.findall(head)
        if not head_toks:
            raise Unsupported("empty declaration")
        ret_ty, name, rest = self.parse_declarator(head_toks)
        if name is None or rest:
            raise Unsupported("could not resolve function name")
        if name in RESERVED_NAMES:
            raise Unsupported(f"`{name}` is a reserved name in Greengold")
        params: list[str] = []
        variadic = False
        ptxt = params_txt.strip()
        if ptxt and ptxt != "void":
            for idx, p in enumerate(self.split_params(ptxt)):
                toks = TOKEN_RE.findall(p)
                if toks == ["..."]:
                    variadic = True
                    continue
                if "(" in toks:  # `int (*cmp)(const void *, const void *)`
                    pname, fty = self.parse_fn_pointer(toks)
                    params.append(f"{self.safe_name(pname) if pname else f'arg{idx}'}: {fty}")
                    continue
                ty, pname, prest = self.parse_declarator(toks)
                dims = self.array_dims(prest)
                if dims:  # `T a[]` / `T a[4]` parameter is a pointer
                    ty = f"*mut {ty}"
                if ty == "void":
                    raise Unsupported("void parametre")
                params.append(f"{self.safe_name(pname) if pname else f'arg{idx}'}: {ty}")
        if variadic:
            params.append("...")
        hdr = f' "{self.header}"' if self.header else ""
        ret = "" if ret_ty == "void" else f" -> {ret_ty}"
        self.funcs.append(f"extern{hdr} fn {name}({', '.join(params)}){ret}")

    def parse_fn_pointer(self, toks: list[str]) -> tuple[str, str]:
        """`ret ( * name ) ( params )` -> (name, `fn(A, B) -> R`)."""
        try:
            open_i = toks.index("(")
        except ValueError:
            raise Unsupported("function pointer") from None
        if open_i + 1 >= len(toks) or toks[open_i + 1] != "*":
            raise Unsupported("function pointer")
        j = open_i + 2
        name = toks[j] if j < len(toks) and re.match(r"[A-Za-z_]\w*$", toks[j]) else ""
        if name:
            j += 1
        if j + 1 >= len(toks) or toks[j] != ")" or toks[j + 1] != "(" or toks[-1] != ")":
            raise Unsupported("function pointer")
        ret_ty, _n, _rest = self.parse_declarator(toks[:open_i] + ["__ret"])
        inner = " ".join(toks[j + 2:-1])
        ptys: list[str] = []
        if inner.strip() and inner.strip() != "void":
            for p in self.split_params(inner):
                ptoks = TOKEN_RE.findall(p)
                if "(" in ptoks or ptoks == ["..."]:
                    raise Unsupported("function pointer with a nested function pointer or `...`")
                pty, _pn, prest = self.parse_declarator(ptoks)
                if self.array_dims(prest):
                    pty = f"*mut {pty}"
                ptys.append(pty)
        ret = "" if ret_ty == "void" else f" -> {ret_ty}"
        return name, f"fn({', '.join(ptys)}){ret}"

    @staticmethod
    def split_params(txt: str) -> list[str]:
        out, depth, cur = [], 0, []
        for ch in txt:
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
            if ch == "," and depth == 0:
                out.append("".join(cur))
                cur = []
            else:
                cur.append(ch)
        out.append("".join(cur))
        return out

    # -- output ----------------------------------------------------------------------------
    def render(self, source_label: str) -> str:
        lines = [f"# Greengold bindings: {source_label} (generated with `gg bindgen`; feel free to edit manually)",
                 "# Functions taking/returning pointers and variadics can only be called inside `unsafe:`."]
        seen_consts: set[str] = set()
        consts = [(n, v) for n, v in self.consts if not (n in seen_consts or seen_consts.add(n))]
        if consts:
            lines.append("")
            for n, v in consts:
                ty = "i32" if -(2 ** 31) <= v < 2 ** 31 else "i64"
                lines.append(f"const {self.safe_name(n)}: {ty} = {v}")
        for ename, members in self.enums:
            lines += ["", f"enum {self.safe_name(ename)}:"]
            lines += [f"    {self.safe_name(n)} = {v}" for n, v in members]
        for sname in self.struct_order:
            st = self.structs[sname]
            if st.fields is None or st.skip_reason or not st.fields:
                continue
            lines += ["", f"union {st.name}:" if st.is_union else f"extern struct {st.name}:"]
            for fname, fty in st.fields:
                note = f"  # {st.comments[fname]}" if fname in st.comments else ""
                lines.append(f"    {fname}: {self.fix_field_type(fty)}{note}")
        if self.funcs:
            lines.append("")
            lines += self.funcs
        if self.notes:
            lines.append("")
            lines += [f"# skipped: {n}" for n in self.notes]
        return "\n".join(lines) + "\n"

    def fix_field_type(self, ty: str) -> str:
        """Resolves `@struct:` placeholders in field types (struct may have been defined later)."""
        def fix(m: re.Match) -> str:
            name = m.group(1)
            st = self.structs.get(name)
            return name if st is not None and st.fields is not None else "void"
        return re.sub(r"@struct:(\w+)", fix, ty)


def bindgen(text: str, header_name: str | None = None, source_label: str | None = None) -> str:
    """Generates Greengold binding source from C header text."""
    b = Binder(header_name)
    prepared = b.preprocess(text)
    for decl in b.split_decls(prepared):
        b.handle(decl)
    return b.render(source_label or header_name or "header")
