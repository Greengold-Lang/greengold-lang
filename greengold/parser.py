"""Handwritten recursive descent parser (precedence climbing / Pratt for expressions).

Error recovery: if an error occurs in a statement, skips to the end of the line
and the parser continues; this allows multiple syntax errors to be reported.
"""
from __future__ import annotations

from .ast_nodes import (
    AllocatorDecl, Apply, Attr, AttrArg, AttrDecl, AttrParam,
    ArrayLit, ArrayRepeatLit, Assign, Binary, Binding, BoolLit, Branch, Break, Call, Cast,
    CharLit, ConstDecl, Continue, EnumDecl, Expr, ExprStmt, ExternFuncDecl, FieldAccess, FieldDecl,
    FieldInit, FloatLit, For, ForIn, FuncDecl, If, IndexAccess, IntLit, Match, MatchArm,
    MethodCall, Name, Node, Param, Pass, Program, Return, SliceExpr, Stmt, StrLit,
    StructDecl, StructLit, Try, TypeApp, TypeRef, Unary, VarDecl, VariantDecl, While, unparse,
    ImportDecl, BlockExpr, Yield, Defer, FeatureDecl, CopyExpr, BorrowExpr, SoaExpr, RangePat, unparse_pat,
    subst_self_func, FormatStr, Require, Wrapping, OverflowMode, walk,
)
import difflib

from .diagnostics import DiagnosticBag, Edit, Fix
from .typeinfo import TYPE_ALIASES, BUILTIN_TYPE_ALIASES, PRIMS
from .lexer import Token, tokenize

NUMERIC_TYPES = {
    "i8", "i16", "i32", "i64", "i128", "u8", "u16", "u32", "u64", "u128",
    "isize", "usize", "f16", "f32", "f64",
}
NUMERIC_CAST_TYPES = NUMERIC_TYPES | {k for k, v in TYPE_ALIASES.items() if v in NUMERIC_TYPES}

WORD_BINARY_OPS = {
    "wrapping_add", "wrapping_sub", "wrapping_mul",
    "saturating_add", "saturating_sub", "saturating_mul",
    "checked_add", "checked_sub", "checked_mul",
}

# Binary operator precedence (higher = binds tighter).
# or(1) < and(2) < not(3, prefix) < comparison(4) < |(5) < ^(6) < &(7) < << >>(8) < + -(9) < * / %(10) < unary - ~(11)
BINARY_PREC = {
    "or": 1, "and": 2,
    "==": 4, "!=": 4, "<": 4, "<=": 4, ">": 4, ">=": 4,
    "|": 5, "^": 6, "&": 7,
    "<<": 8, ">>": 8,
    "+": 9, "-": 9,
    "wrapping_add": 9, "wrapping_sub": 9,
    "saturating_add": 9, "saturating_sub": 9,
    "checked_add": 9, "checked_sub": 9,
    "*": 10, "/": 10, "%": 10,
    "wrapping_mul": 10, "saturating_mul": 10, "checked_mul": 10,
}
COMPARE_OPS = {"==", "!=", "<", "<=", ">", ">="}
ASSIGN_OPS = ("=", "+=", "-=", "*=", "/=", "%=", "&=", "|=", "^=", "<<=", ">>=")

PARAM_MODES = ("consume", "read", "lend")
MAX_TUPLE = 6

_REF_MSG = {
    "variable": "`{kw}` cannot be stored as an owned value; write `name: read T = ...` or `name: lend T = ...`.",
    "field": "`{kw}` cannot be a struct field; it can only be a function parameter (use `tied to` for field).",
    "return": "`{kw}` cannot be a return type; it can only be a function parameter.",
    "payload": "`{kw}` cannot be an enum payload; it can only be a function parameter.",
    "type argument": "`{kw}` cannot be a type argument; it can only be a function parameter.",
    "parameter": "`{kw}` cannot be a parameter type; write without `{kw}`.",
}


class ParseError(Exception):
    """Error already recorded in `diags`; this exception only aborts flow."""


class Parser:
    def __init__(self, tokens: list[Token], diags: DiagnosticBag, filename: str | None = None) -> None:
        self.toks = tokens
        self.pos = 0
        self.diags = diags
        self.filename = filename
        self.bounds: dict = {}  # last read `T: Feature` bounds from `_type_params`
        self.tmp_counter = 0
        self.lambda_counter = 0
        self.lifted: list[FuncDecl] = []
        self.uses_tasks = False  # `async fn` or `await` seen: std.tasks is imported for them
        # Type parameters of the generic function whose body is being read: a lambda in it is generic too.
        self._outer_generic: tuple[list[str], dict] = ([], {})
        self.aliases: dict[str, TypeRef] = {}
        self._pat_only = False  # `_arm_rest` stops after the pattern (used by `if let` / `while let`)
        self._test_target = ""
        self._test_serial = 0
        self._test_labels: dict[str, int] = {}
        # `public` / `private` on their own line. Everything after follows until the next switch.
        # A file starts public.
        self._export = True
        # Statements and declarations dropped by error recovery: the names they mentioned and their lines.
        # The type checker still runs; its diagnostics about these names are cascades of the syntax error.
        self.skips: list[dict] = []
        self._globals: set[str] = {
            tokens[i + 1].text
            for i in range(len(tokens) - 1)
            if tokens[i].kind in ("const", "static") and tokens[i + 1].kind == "NAME"
        }
        self._scopes: list[set[str]] = [set()]
        self._pending_bindings: set[str] = set()

    def _in_scope(self, name: str) -> bool:
        return name in self._globals or any(name in s for s in self._scopes)

    # -- token helpers ----------------------------------------------
    @property
    def tok(self) -> Token:
        return self.toks[self.pos]

    @property
    def prev(self) -> Token:
        return self.toks[self.pos - 1]

    def _peek(self, n: int = 1) -> Token:
        return self.toks[min(self.pos + n, len(self.toks) - 1)]

    def _advance(self) -> Token:
        t = self.tok
        if t.kind != "EOF":
            self.pos += 1
        return t

    def _check(self, *kinds: str) -> bool:
        return self.tok.kind in kinds

    def _match(self, *kinds: str) -> Token | None:
        return self._advance() if self.tok.kind in kinds else None

    @staticmethod
    def _describe(tok: Token) -> str:
        return {"NEWLINE": "newline", "INDENT": "indent", "DEDENT": "dedent",
                "EOF": "end of file"}.get(tok.kind, f"`{tok.text}`")

    def _error(self, tok: Token | Node, msg: str, hint: str | None = None,
               fixes: list[Fix] | None = None) -> ParseError:
        """Records error and returns exception to raise: `raise self._error(...)`."""
        self.diags.error(msg, tok.line, tok.col, max(tok.length, 1), hint,
                         filename=self.filename, fixes=fixes)
        return ParseError()

    def _soft_error(self, node: Token | Node, msg: str, hint: str | None = None) -> None:
        """Records error but continues parsing."""
        self.diags.error(msg, node.line, node.col, max(node.length, 1), hint)

    def _replace_word_fix(self, word: Token, text: str, description: str) -> Fix:
        """Replaces keyword `word` and the spaces after it with `text` (empty: deletes it)."""
        end = word.col + len(word.text)
        if not text:
            i = self.toks.index(word)
            nxt = self.toks[i + 1] if i + 1 < len(self.toks) else word
            if nxt.line == word.line and nxt.col > end:
                end = nxt.col
        return Fix(description, "safe", [Edit(word.line, word.col, word.line, end, text, self.filename)])

    _FOREIGN_FN = ("def", "func", "function", "fun")

    def _foreign_fn_word(self) -> bool:
        """`def f(...)` / `func f(...)`: report it with a fix and read it as `fn`."""
        t = self.tok
        if not (t.kind == "NAME" and t.text in self._FOREIGN_FN and self._peek().kind == "NAME"
                and self._peek(2).kind in ("(", "[")):
            return False
        self.diags.error(f"`{t.text}` is not Greengold syntax; write `fn`.", t.line, t.col, len(t.text),
                         "A function starts with `fn`.", filename=self.filename,
                         fixes=[self._replace_word_fix(t, "fn", f"Replace `{t.text}` with `fn`")])
        self.toks[self.pos] = Token("fn", "fn", t.line, t.col, t.length)
        return True

    def _let_stmt(self) -> Stmt:
        """`let x = v` / `let mut x = v` / `let x: T = v`: reported with a fix, then read as a declaration."""
        let = self._advance()
        if self.tok.kind == "NAME" and self.tok.text == "mut" and self._peek().kind == "NAME":
            self._advance()
        name = self.tok
        hint = "A new variable is `name = value`. It can be changed unless it is `fixed`."
        if self._peek().kind == "=":
            eq = self._peek()
            self.diags.error("`let` is not Greengold syntax; write `name = value`.", let.line, let.col, len(let.text),
                             hint, filename=self.filename,
                             fixes=[Fix(f"Write `{name.text} = ...`", "safe",
                                        [Edit(let.line, let.col, eq.line, eq.col + 1, f"{name.text} =", self.filename)])])
            self._advance()  # name
            self._advance()  # =
            value = self._expr()
            node = self._at(VarDecl(name.text, True, None, value), name)
            node.is_soa = isinstance(value, SoaExpr)  # type: ignore[attr-defined]
            self._scopes[-1].add(name.text)
            self._end_stmt()
            return node  # type: ignore[return-value]
        self.diags.error("`let` is not Greengold syntax; write `name: T = value`.", let.line, let.col, len(let.text),
                         hint, filename=self.filename,
                         fixes=[Fix("Delete `let`", "safe", [Edit(let.line, let.col, name.line, name.col, "", self.filename)])])
        return self._var_decl()

    def _block_colon(self, msg: str, hint: str) -> None:
        """The `:` that opens a block. When the line simply ends, say so, offer the fix, and keep parsing."""
        if self._match(":"):
            return
        if self._check("NEWLINE") and self.pos > 0:
            prev = self.prev
            end = prev.col + max(prev.length, len(prev.text))
            self.diags.error(f"{msg} (found newline)", self.tok.line, self.tok.col, 1, hint, filename=self.filename,
                             fixes=[Fix("Add `:` at the end of the line", "safe",
                                        [Edit(prev.line, end, prev.line, end, ":", self.filename)])])
            return
        self._expect(":", msg, hint)

    def _keyword_typo_fix(self, expr: Expr) -> tuple[str | None, list[Fix]]:
        """`retrun x` reads as a name followed by junk. Offer the keyword it is closest to."""
        if not isinstance(expr, Name):
            return None, []
        words = ["return", "break", "continue", "pass", "while", "for", "match", "defer", "require", "elif", "else"]
        near = difflib.get_close_matches(expr.name, words, n=1, cutoff=0.7)
        if not near:
            return None, []
        return near[0], [Fix(f"Replace `{expr.name}` with `{near[0]}`", "likely",
                             [Edit(expr.line, expr.col, expr.line, expr.col + len(expr.name), near[0], self.filename)])]

    def _impl_move_fix(self, fn_index: int, first: Token, second: Token, type_name: str) -> list[Fix]:
        """`fn P.get(...)`: wrap the function in `impl P:` and indent it one level."""
        i = self.pos
        while i < len(self.toks) and self.toks[i].kind not in ("NEWLINE", "EOF"):
            i += 1
        if i + 1 >= len(self.toks) or self.toks[i + 1].kind != "INDENT":
            return []
        depth = 0
        j = i + 1
        last_line = self.toks[fn_index].line
        while j < len(self.toks):
            k = self.toks[j].kind
            if k == "INDENT":
                depth += 1
            elif k == "DEDENT":
                depth -= 1
                if depth == 0:
                    break
            elif k not in ("NEWLINE", "EOF"):
                last_line = max(last_line, self.toks[j].line)
            j += 1
        fn_tok = self.toks[fn_index]
        lines = sorted({t.line for t in self.toks[fn_index:j] if t.kind not in ("INDENT", "DEDENT", "NEWLINE", "EOF")
                        and fn_tok.line <= t.line <= last_line})
        edits = [Edit(fn_tok.line, 1, fn_tok.line, 1, f"impl {type_name}:\n    ", self.filename),
                 Edit(first.line, first.col, second.line, second.col, "", self.filename)]
        edits += [Edit(line, 1, line, 1, "    ", self.filename) for line in lines if line != fn_tok.line]
        return [Fix(f"Move `{second.text}` into `impl {type_name}:`", "safe", edits)]

    def _removed_var(self) -> None:
        """`var x := 5` / `for var x in xs`: reports the removed keyword, skips it and keeps parsing."""
        word = self._advance()
        self.diags.error(
            "`var` was removed: variables can be changed by default.",
            word.line, word.col, len(word.text),
            "Delete `var`. Write `fixed x = ...` for a variable that must never change.",
            filename=self.filename,
            fixes=[self._replace_word_fix(word, "", "Delete `var`")],
        )

    def _removed_walrus(self, tok: Token) -> None:
        """`x := 5`: the `:=` operator was removed; report it with a fix (the caller reads it as `=`)."""
        self.diags.error(
            "`:=` was removed: write `=` to declare a variable.",
            tok.line, tok.col, 2,
            "A new variable is `name = value`; with a type it is `name: type = value`.",
            filename=self.filename,
            fixes=[Fix("Replace `:=` with `=`", "safe", [Edit(tok.line, tok.col, tok.line, tok.col + 2, "=", self.filename)])],
        )

    def _fix_walrus_in_line(self) -> None:
        """A statement like `[var|fixed] a[, b] := v`: report `:=` and turn it into `=`."""
        i = self.pos
        if self.toks[i].kind in ("var", "fixed"):
            i += 1
        while self.toks[i].kind == "NAME":
            i += 1
            if self.toks[i].kind != ",":
                break
            i += 1
        t = self.toks[i]
        if t.kind == ":=":
            self._removed_walrus(t)
            self.toks[i] = Token("=", "=", t.line, t.col, 1)

    def _expect(self, kind: str, msg: str, hint: str | None = None) -> Token:
        if self.tok.kind == kind:
            return self._advance()
        fixes = self._missing_indent_fixes() if kind == "INDENT" else None
        raise self._error(self.tok, f"{msg} (found {self._describe(self.tok)})", hint, fixes=fixes)

    def _line_start_col(self, index: int) -> int | None:
        """Column of the first code token on the line that contains `index`."""
        if index < 0 or index >= len(self.toks):
            return None
        line = self.toks[index].line
        i = index
        while i >= 0 and self.toks[i].line == line:
            i -= 1
        i += 1
        while i < len(self.toks) and self.toks[i].kind in ("INDENT", "DEDENT", "NEWLINE"):
            i += 1
        if i >= len(self.toks) or self.toks[i].line != line:
            return None
        return self.toks[i].col

    def _missing_indent_fixes(self) -> list[Fix] | None:
        """The body line is present but not indented. The only legal indent is the opener plus four."""
        if self.tok.kind in ("NEWLINE", "DEDENT", "EOF", "INDENT"):
            return None
        opener = self.pos - 1
        while opener >= 0 and self.toks[opener].kind == "NEWLINE":
            opener -= 1
        if opener < 0:
            return None
        origin = self._line_start_col(opener)
        if origin is None:
            return None
        spaces = origin - 1 + 4
        return [Fix(
            f"Indent with {spaces} spaces",
            "safe",
            [Edit(self.tok.line, 1, self.tok.line, self.tok.col, " " * spaces, self.filename)],
        )]

    def _unexpected_indent_fixes(self) -> list[Fix] | None:
        """This line was indented, and the previous line did not open a block. Line it up with that line."""
        content = self.pos + 1
        while content < len(self.toks) and self.toks[content].kind in ("NEWLINE", "INDENT", "DEDENT"):
            content += 1
        if content >= len(self.toks):
            return None
        prev = self.pos - 1
        while prev >= 0 and self.toks[prev].kind in ("NEWLINE", "INDENT", "DEDENT"):
            prev -= 1
        if prev < 0:
            return None
        origin = self._line_start_col(prev)
        if origin is None:
            return None
        spaces = origin - 1
        token = self.toks[content]
        if token.col - 1 == spaces:
            return None
        return [Fix(
            f"Indent with {spaces} spaces",
            "safe",
            [Edit(token.line, 1, token.line, token.col, " " * spaces, self.filename)],
        )]

    def _at(self, node: Node, start: Token | Node) -> Node:
        """Sets node location from `start` to last consumed token."""
        node.line, node.col = start.line, start.col
        if self.filename is not None:
            node.filename = self.filename
        prev = self.prev
        if prev.line == start.line:
            node.length = max(1, prev.col + prev.length - start.col)
        else:
            node.length = max(start.length, 1)
        return node

    # -- error recovery ---------------------------------------------
    def _skip_block(self) -> None:
        """Currently on INDENT: skip to matching DEDENT."""
        depth = 0
        while self.tok.kind != "EOF":
            if self.tok.kind == "INDENT":
                depth += 1
            elif self.tok.kind == "DEDENT":
                depth -= 1
                if depth == 0:
                    self._advance()
                    return
            self._advance()

    def _record_skip(self, start: int, top: bool = False) -> None:
        """Remember what error recovery threw away between token `start` and the current token."""
        toks = [t for t in self.toks[start:max(self.pos, start + 1)] if t.kind not in ("INDENT", "DEDENT", "NEWLINE", "EOF")]
        if not toks:
            return
        self.skips.append({
            "names": {t.text for t in toks if t.kind == "NAME"},
            "first": toks[0].line,
            "last": toks[-1].line,
            "top": top,
        })

    def _sync_stmt(self) -> None:
        """Skip erroneous statement: up to newline (and indented block if any)."""
        start = self.pos
        try:
            self._sync_stmt_inner()
        finally:
            # The statement began before the error token; take the whole line it started on.
            begin = start
            while begin > 0 and self.toks[begin - 1].line == self.toks[start].line \
                    and self.toks[begin - 1].kind not in ("NEWLINE", "INDENT", "DEDENT"):
                begin -= 1
            self._record_skip(begin)

    def _sync_stmt_inner(self) -> None:
        if self._check("INDENT"):
            self._skip_block()
            return
        while not self._check("NEWLINE", "DEDENT", "EOF"):
            self._advance()
        if self._match("NEWLINE") and self._check("INDENT"):
            self._skip_block()

    def _sync_top(self, start: int) -> None:
        """Skip to next `fn`/`struct` declaration at top-level."""
        try:
            self._sync_top_inner(start)
        finally:
            self._record_skip(start, top=True)

    def _sync_top_inner(self, start: int) -> None:
        if self.pos == start:
            self._advance()
        depth = 0
        while self.tok.kind != "EOF":
            k = self.tok.kind
            if k == "INDENT":
                depth += 1
            elif k == "DEDENT":
                depth = max(0, depth - 1)
            elif depth == 0 and self.prev.kind in ("NEWLINE", "DEDENT"):
                if k in ("fn", "struct", "enum", "feature", "const", "extern", "import", "comptime",
                         "public", "private", "hot", "async", "@"):
                    return
                if k == "NAME" and self.tok.text == "test" and self._peek().kind in (":", "NAME"):
                    return
            self._advance()

    # -- program ----------------------------------------------------
    def parse_program(self) -> Program:
        decls: list[Node] = []
        while not self._check("EOF"):
            start = self.pos
            try:
                if self._check("public", "private"):
                    self._visibility_section()
                    continue
                # A `private` inside the body must not flip this declaration itself.
                export_here = self._export
                made: Node | None = None
                attrs = self._attr_lines()
                if attrs and self._check("public", "private"):
                    raise self._error(self.tok, "Put `public` or `private` on its own line above the attributes.")
                if self._check("struct"):
                    made = self._struct_decl()
                elif self._check("enum"):
                    made = self._enum_decl()
                elif self._check("feature"):
                    made = self._feature_decl()
                elif self._check("fn"):
                    made = self._func_decl()
                elif self._foreign_fn_word():
                    made = self._func_decl()
                elif self._check("comptime"):
                    self._advance()
                    if not self._check("fn"):
                        raise self._error(self.tok, "Expected `fn` after `comptime`.",
                                          "Write in the form `comptime fn name() -> T:`.")
                    fd = self._func_decl()
                    fd.is_comptime = True
                    made = fd
                elif self._check("hot"):
                    self._advance()
                    if not self._check("fn"):
                        raise self._error(self.tok, "Expected `fn` after `hot`.",
                                          "Write in the form `hot fn name(...):`.")
                    fd = self._func_decl()
                    fd.is_hot = True
                    made = fd
                elif self._check("async"):
                    self._advance()
                    if not self._check("fn"):
                        raise self._error(self.tok, "Expected `fn` after `async`.",
                                          "Write in the form `async fn name(...) -> T:`.")
                    header_at = self.pos
                    fd = self._func_decl()
                    if fd.name == "main":  # the program itself is the first task
                        made = fd
                    else:
                        for extra in self._async_fn(fd, header_at):
                            extra.is_pub = export_here
                            decls.append(extra)
                        made = fd
                elif self._check("const"):
                    made = self._const_decl()
                elif self.tok.kind == "NAME" and self.tok.text == "static" and self._peek().kind == "NAME":
                    made = self._const_decl()  # `static NAME: T = value`
                    made.is_static = True
                elif (self.tok.kind == "NAME" and self.tok.text == "allocator" and self._peek().kind == "NAME"
                      and self._peek(2).kind == ","):
                    start = self._advance()
                    names = [self._expect("NAME", "Expected a function name").text]
                    for _ in range(2):
                        self._expect(",", "`allocator` names three functions: alloc, resize, free")
                        names.append(self._expect("NAME", "Expected a function name").text)
                    self._end_stmt()
                    made = self._at(AllocatorDecl(*names), start)
                elif self.tok.kind == "NAME" and self.tok.text == "union" and self._peek().kind == "NAME":
                    sd = self._struct_decl()  # `union Bits:` reads like a struct
                    sd.is_union = True
                    made = sd
                elif self.tok.kind == "NAME" and self.tok.text == "packed" and self._peek().kind == "struct":
                    self._advance()
                    sd = self._struct_decl()
                    sd.packed = True
                    made = sd
                elif (self.tok.kind == "NAME" and self.tok.text == "align" and self._peek().kind == "("
                      and self._peek(2).kind == "INT" and self._peek(3).kind == ")" and self._peek(4).kind == "struct"):
                    self._advance()
                    self._advance()
                    n_tok = self._advance()
                    self._advance()
                    sd = self._struct_decl()
                    sd.align = int(str(n_tok.text).replace("_", ""), 0)
                    if sd.align not in (1, 2, 4, 8, 16, 32, 64):
                        self._soft_error(n_tok, "`align(N)` takes a power of two from 1 to 64.")
                        sd.align = 0
                    made = sd
                elif self._check("extern") and self._peek().kind == "struct":
                    self._advance()  # extern
                    sd = self._struct_decl()
                    sd.is_extern = True
                    made = sd
                elif self._check("extern"):
                    made = self._extern_decl()
                elif self.tok.kind == "NAME" and self.tok.text == "weak" and self._peek().kind == "extern":
                    self._advance()
                    made = self._extern_decl()
                    made.weak = True
                elif self._check("import"):
                    decls.append(self._import_decl())
                elif self.tok.kind == "NAME" and self.tok.text == "impl" and self._peek().kind == "NAME":
                    decls.extend(self._impl_block())
                elif self.tok.kind == "NAME" and self.tok.text == "type" and self._peek().kind == "NAME" \
                        and self._peek(2).kind == "=":
                    self._type_alias()
                elif self._check("var"):
                    raise self._error(self.tok, "`var` was removed: a top-level value is a constant.",
                                      "Write `const NAME = value`.",
                                      fixes=[self._replace_word_fix(self.tok, "const", "Write `const` instead of `var`")])
                elif self.tok.kind == "NAME" and self.tok.text == "test" and self._peek().kind in (":", "NAME"):
                    decls.append(self._test_block())
                elif self.tok.kind == "NAME" and self.tok.text == "attribute" and self._peek().kind == "NAME":
                    made = self._attribute_decl()
                else:
                    raise self._error(
                        self.tok,
                        f"Only `struct`, `enum`, `feature`, `impl`, `fn`, `test`, `const`, `extern`, and `import` can be declared at top-level (found {self._describe(self.tok)}).",
                        "Put code inside a `fn`; program entry point must be `fn main():`.")
                if attrs:
                    if isinstance(made, (FuncDecl, StructDecl)) or (isinstance(made, ConstDecl) and made.is_static):
                        made.attrs = attrs
                    else:
                        self._soft_error(attrs[0], "An attribute goes on a `fn`, a `struct`, a `static`, or a struct field.",
                                         "Write the `@name` line directly above one of those.")
                if made is not None:
                    made.is_pub = export_here
                    decls.append(made)
            except ParseError:
                self._sync_top(start)
        decls.extend(self._enum_number_methods(decls))
        decls.extend(self.lifted)
        if self.uses_tasks and not any(isinstance(d, ImportDecl) and d.alias == "_gg_tasks" for d in decls):
            decls.insert(0, ImportDecl("std/tasks.gg", alias="_gg_tasks", line=1, col=1, filename=self.filename))
        if self.aliases:
            self._resolve_aliases(decls)
        if self.filename is not None:
            for d in decls:
                if getattr(d, "filename", None) is None:
                    d.filename = self.filename
        prog = Program(decls, line=1, col=1, filename=self.filename)
        prog.syntax_skips = self.skips  # type: ignore[attr-defined]
        return prog

    # -- async fn ----------------------------------------------------
    def _async_fn(self, fd: FuncDecl, header_at: int) -> list[FuncDecl]:
        """`async fn f(a: A) -> T:` keeps its body as `__async_f` and adds `fn f(a: A) -> Task[T]`, which
        starts that body as a task (`std.tasks.spawn`) with the arguments moved into it. A function
        without a result gives a `Task[bool]`."""
        self.uses_tasks = True
        name = fd.name
        bad = False
        for p in fd.params:
            if p.mode in ("read", "lend"):
                self._soft_error(p, f"A parameter of an `async fn` cannot be `{p.mode}`: the task may run after "
                                    "the caller has moved on.",
                                 "Take the value itself (it moves into the task), or an `Arc` to share it.")
                bad = True
        if bad:  # left as a plain function, so the error above is the only one
            return []
        # The header as written, from `fn` to the `:` that opens the body.
        toks = self.toks[header_at:]
        depth, end = 0, 0
        for i, t in enumerate(toks):
            if t.kind in ("(", "["):
                depth += 1
            elif t.kind in (")", "]"):
                depth -= 1
            elif t.kind == ":" and depth == 0:
                end = i
                break
        head = toks[:end]
        arrow = next((i for i, t in enumerate(head) if t.kind == "->"), len(head))
        params_text = " ".join(t.text for t in head[2:arrow])  # `[T](a: A, b: B)` after `fn name`
        ret_text = " ".join(t.text for t in head[arrow + 1:]) if arrow < len(head) else ""
        body = f"__async_{name}"
        fd.name = body
        targs = f"[{', '.join(fd.type_params)}]" if fd.type_params else ""
        if not ret_text:  # no result: the body returns `true`, and the task is a `Task[bool]`
            ret_text = "bool"
            fd.ret = self._at(TypeRef("bool"), fd)
            for n in walk(fd.body):
                if isinstance(n, Return) and n.value is None:
                    n.value = self._at(BoolLit(True), n)
            if not fd.body or not isinstance(fd.body[-1], Return):
                fd.body.append(self._at(Return(self._at(BoolLit(True), fd)), fd))
        # Each argument moves into its own slot on the heap; the task takes it back once. (A lambda that
        # captured the arguments themselves could not hand them on: a `Fn` may be called again.)
        open_at = next(i for i, t in enumerate(head) if t.kind == "(")
        pieces: list[list] = [[]]
        depth = 0
        for t in head[open_at + 1:arrow]:
            if t.kind in ("(", "["):
                depth += 1
            elif t.kind in (")", "]"):
                if depth == 0:
                    break
                depth -= 1
            if t.kind == "," and depth == 0:
                pieces.append([])
            else:
                pieces[-1].append(t)
        types = []
        for piece in pieces:
            if not piece:
                continue
            rest = piece[2:]  # after `name :`
            while rest and rest[0].kind in ("consume", "exclusive"):
                rest = rest[1:]
            types.append(" ".join(t.text for t in rest))
        lines = [f"fn {name}{params_text} -> _gg_tasks.Task[{ret_text}]:"]
        for i, p in enumerate(fd.params):
            lines.append(f"    __arg{i} = _gg_tasks._park({p.name})")
        taken = ", ".join(f"_gg_tasks._unpark[{ty}](__arg{i})" for i, ty in enumerate(types))
        lines.append(f"    return _gg_tasks.spawn(fn() -> {ret_text} => {body}{targs}({taken}))")
        src = "\n".join(lines) + "\n"
        saved = (self.toks, self.pos)
        before = len(self.lifted)
        made: list[FuncDecl] = []
        try:
            self.toks, self.pos = tokenize(src, self.diags), 0
            while not self._check("EOF"):
                if self._check("NEWLINE"):
                    self._advance()
                    continue
                made.append(self._func_decl())
        finally:
            self.toks, self.pos = saved
        for d in made + self.lifted[before:]:
            _relocate(d, fd)
        if made:
            made[0].async_wrapper = True  # type: ignore[attr-defined]  # its parameters must be able to move to a task
        return made

    # -- type aliases ------------------------------------------------
    def _type_alias(self) -> None:
        """`type Name = Type` (top-level). Aliases are expanded away after parsing."""
        self._advance()  # type
        name = self._expect("NAME", "Expected alias name")
        self._expect("=", "Expected `=` in type alias")
        target = self._type("variable")
        self._end_stmt()
        if name.text in self.aliases or name.text in PRIMS or name.text in BUILTIN_TYPE_ALIASES:
            raise self._error(name, f"Type alias `{name.text}` is already defined.")
        self.aliases[name.text] = target

    def _resolve_aliases(self, decls: list[Node]) -> None:
        import copy
        resolving: set[str] = set()

        def expand(t: TypeRef) -> None:
            for sub in [t.elem, *t.args, *t.fn_params, t.fn_ret]:
                if sub is not None:
                    expand(sub)
            if t.is_fn:
                t.name = f"fn({', '.join(p.name for p in t.fn_params)})" + (f" -> {t.fn_ret.name}" if t.fn_ret else "")
                return
            if t.base is None and t.name in self.aliases and not t.args:
                if t.name in resolving:
                    self._soft_error(t, f"Type alias `{t.name}` refers to itself.")
                    return
                resolving.add(t.name)
                target = copy.deepcopy(self.aliases[t.name])
                expand(target)
                resolving.discard(t.name)
                keep = (t.line, t.col, t.length, t.filename)
                t.__dict__.update(target.__dict__)
                t.line, t.col, t.length, t.filename = keep
            elif t.args:
                t.name = f"{t.base}[{', '.join(a.name for a in t.args)}]"
            elif t.elem is not None:
                if t.is_ptr:
                    t.name = f"*mut {t.elem.name}" if t.ptr_mut else f"*{t.elem.name}"
                elif t.is_slice:
                    t.name = f"[]{t.elem.name}"
                elif t.is_array and t.size_expr is not None:
                    t.name = f"[{unparse(t.size_expr)}]{t.elem.name}"

        def walk(n: object) -> object:
            """Expands aliases inside `n`; returns the node to use in its place."""
            if isinstance(n, TypeRef):
                expand(n)
                if n.size_expr is not None:
                    walk(n.size_expr)
                return n
            if isinstance(n, StructLit) and n.type_name in self.aliases and not n.type_args:
                target = self.aliases[n.type_name]
                if target.base is not None:
                    n.type_name = target.base
                    n.type_args = [copy.deepcopy(a) for a in target.args]
                else:
                    n.type_name = target.name
            if isinstance(n, Call) and n.callee in self.aliases and not n.type_args:
                target = self.aliases[n.callee]
                for a in n.args:
                    walk(a)
                if target.base is None and target.name in NUMERIC_TYPES and len(n.args) == 1:
                    return self._at(Cast(target.name, n.args[0]), n)
                if target.base is not None:
                    n.callee = target.base
                    n.type_args = [copy.deepcopy(a) for a in target.args]
                else:
                    n.callee = target.name
                return n
            if isinstance(n, Node):
                for k, v in list(n.__dict__.items()):
                    nv = walk(v)
                    if nv is not v:
                        setattr(n, k, nv)
            elif isinstance(n, list):
                for i, x in enumerate(n):
                    nx = walk(x)
                    if nx is not x:
                        n[i] = nx
            elif isinstance(n, dict):
                for k, x in list(n.items()):
                    nx = walk(x)
                    if nx is not x:
                        n[k] = nx
            return n

        for a in self.aliases.values():
            walk(a)
        for d in decls:
            walk(d)

    # -- impl blocks ---------------------------------------------------
    def _impl_block(self) -> list[Node]:
        """`impl Name[A, B]:` + indented `fn method(self, ...)`: sugar for `fn Name[A, B].method(...)`."""
        self._advance()  # impl
        name = self._expect("NAME", "Expected type name after `impl`")
        owner_qualifier = None
        if self._check(".") and self._peek().kind == "NAME":  # `impl combat.Hero`
            self._advance()
            member = self._expect("NAME", "Expected type name after `.`")
            owner_qualifier = name.text
            name = member
        params = self._type_params() if self._check("[") else []
        self._expect(":", "Expected `:` after impl header", "Write in the form `impl Player:`.")
        self._expect("NEWLINE", "Methods must be written on indented lines after `:`")
        self._expect("INDENT", "Methods must be indented with 4 spaces")
        out: list[Node] = []
        while not self._check("DEDENT", "EOF"):
            start = self.pos
            try:
                if self._check("public", "private"):
                    self._visibility_section()
                    continue
                is_hot = False
                mattrs = self._attr_lines()
                if self._check("async"):
                    raise self._error(self.tok, "A method cannot be `async`.",
                                      "Write an `async fn` outside the `impl` that takes the value as a parameter.")
                if self._check("hot"):
                    self._advance()
                    is_hot = True
                if not self._check("fn") and not self._foreign_fn_word():
                    raise self._error(self.tok, "Only `fn` definitions can be written inside an `impl` block.")
                fd = self._func_decl(impl=(name.text, params), owner_qualifier=owner_qualifier)
                fd.is_hot = is_hot
                fd.attrs = mattrs
                fd.is_pub = self._export
                out.append(fd)
            except ParseError:
                self._sync_stmt()
                if self.pos == start:
                    self._advance()
        self._match("DEDENT")
        return out

    # -- attributes -------------------------------------------------
    _ATTR_KINDS = ("str", "int", "float", "bool", "ident")

    def _attr_lines(self) -> list[Attr]:
        """Zero or more `@name` / `@name(args)` lines. Each stands on its own line."""
        out: list[Attr] = []
        while self._check("@"):
            at = self._advance()
            name = self._expect("NAME", "Expected an attribute name after `@`",
                                "Write `@name` or `@name(args)`.")
            args: list[AttrArg] = []
            if self._match("("):
                while not self._check(")"):
                    args.append(self._attr_arg())
                    if not self._match(","):
                        break
                self._expect(")", "Expected `)` after the attribute arguments")
            out.append(self._at(Attr(name.text, args), at))  # type: ignore[arg-type]
            self._end_stmt()
        return out

    def _attr_arg(self) -> AttrArg:
        """A string, number, `true`/`false`, or a bare name; optionally `key=` in front."""
        start = self.tok
        key = None
        if start.kind == "NAME" and self._peek().kind == "=":
            key = start.text
            self._advance()
            self._advance()
        t = self.tok
        neg = False
        if t.kind == "-" and self._peek().kind in ("INT", "FLOAT"):
            neg = True
            self._advance()
            t = self.tok
        value: object
        if t.kind == "INT":
            kind, value = "int", int(t.text)
        elif t.kind == "FLOAT":
            kind, value = "float", float(str(t.text).replace("_", ""))
        elif t.kind == "STRING":
            kind, value = "str", t.text
        elif t.kind in ("true", "false"):
            kind, value = "bool", t.kind == "true"
        elif t.kind == "NAME":
            kind, value = "ident", t.text
        else:
            raise self._error(t, f"An attribute argument is a string, a number, `true`/`false`, or a name (found {self._describe(t)}).")
        self._advance()
        if neg:
            value = -value  # type: ignore[operator]
        return self._at(AttrArg(kind, value, name=key), start)  # type: ignore[return-value]

    def _attribute_decl(self) -> AttrDecl:
        """`attribute name(p: kind, q: kind = default) on fn, struct, field`."""
        start = self._advance()  # attribute
        name = self._expect("NAME", "Expected the attribute name")
        params: list[AttrParam] = []
        if self._match("("):
            while not self._check(")"):
                pname = self._expect("NAME", "Expected a parameter name")
                self._expect(":", "Missing parameter kind", "Write `name: str`, `int`, `float`, `bool`, or `ident`.")
                kt = self._expect("NAME", "Expected the parameter kind")
                if kt.text not in self._ATTR_KINDS:
                    raise self._error(kt, f"`{kt.text}` is not an attribute parameter kind.",
                                      "Use `str`, `int`, `float`, `bool`, or `ident` (a bare name such as `server`).")
                default = None
                if self._match("="):
                    default = self._attr_arg()
                params.append(self._at(AttrParam(pname.text, kt.text, default=default), pname))  # type: ignore[arg-type]
                if not self._match(","):
                    break
            self._expect(")", "Expected `)` after the attribute parameters")
        targets: list[str] = []
        if self.tok.kind == "NAME" and self.tok.text == "on":
            self._advance()
            while True:
                tt = self.tok
                if tt.kind not in ("fn", "struct") and not (tt.kind == "NAME" and tt.text == "field"):
                    raise self._error(tt, "An attribute goes on `fn`, `struct`, or `field`.",
                                      "Write `on fn`, `on struct`, `on field`, or a list such as `on fn, field`.")
                self._advance()
                targets.append(tt.text)
                if not self._match(","):
                    break
        decl = self._at(AttrDecl(name.text, params, targets=targets), start)
        if self._check(":"):
            decl.handler = self._attribute_handler(name, params)  # type: ignore[attr-defined]
            self.lifted.append(decl.handler)  # type: ignore[attr-defined]
        else:
            self._end_stmt()
        return decl  # type: ignore[return-value]

    _ATTR_TYPES = {"str": "str", "int": "i64", "float": "f64", "bool": "bool", "ident": "str"}
    ATTR_TARGET_PARAMS = ("target_kind", "target_name", "target_owner", "target_type")

    def _attribute_handler(self, name: Token, params: list[AttrParam]) -> FuncDecl:
        """The body under `attribute name(...) on fn:` becomes `comptime fn __attr_name(...)`. It runs once for each
        use, with the arguments as variables and `target_*` describing the item the attribute sits on."""
        fparams = [self._at(Param(p.name, self._at(TypeRef(self._ATTR_TYPES[p.kind]), name)), name) for p in params]
        fparams += [self._at(Param(t, self._at(TypeRef("str"), name)), name) for t in self.ATTR_TARGET_PARAMS]
        prev_scopes = self._scopes
        self._scopes = [{p.name for p in fparams}]
        try:
            body = self._block()
        finally:
            self._scopes = prev_scopes
        fd = self._at(FuncDecl(f"__attr_{name.text}", None, fparams, None, body), name)
        fd.is_comptime = True  # type: ignore[attr-defined]
        fd.attr_handler = True  # type: ignore[attr-defined]
        return fd  # type: ignore[return-value]

    def _visibility_section(self) -> None:
        """A line that is only `public` or `private` sets visibility for what follows."""
        word = self._advance()
        if not self._check("NEWLINE", "EOF"):
            raise self._error(
                word,
                f"`{word.text}` stands on its own line.",
                "Write it alone. Declarations below stay public or private until the next line.",
            )
        self._export = word.kind == "public"
        self._match("NEWLINE")

    def _import_decl(self) -> ImportDecl:
        imp_tok = self._advance()  # import
        if self._check("STRING"):
            tok = self._advance()
            path = tok.text
        elif self._check("NAME"):
            tok = self._advance()
            parts = [tok.text]
            while self._check(".") and self._peek().kind == "NAME":  # `import std.math` -> "std/math.gg"
                self._advance()
                parts.append(self._advance().text)
            path = "/".join(parts) + ".gg"
        else:
            raise self._error(self.tok, "Expected file name (string) or module name after import.",
                              hint='Example: `import "file.gg"` or `import module`')
        alias: str | None = None
        names: list[str] = []
        if self.tok.kind == "NAME" and self.tok.text == "as":
            self._advance()
            alias_tok = self._expect("NAME", "Expected module name after `as`",
                                     "Example: `import std.math as m`.")
            alias = alias_tok.text
        elif self._match("{"):
            if self._check("}"):
                raise self._error(self.tok, "Selective import list cannot be empty.",
                                  "Example: `import std.math { sqrt, sin }`.")
            while True:
                item = self._expect("NAME", "Expected name in import list")
                names.append(item.text)
                if not self._match(","):
                    break
            self._expect("}", "Expected `}`")
        self._end_stmt()
        return self._at(ImportDecl(path, alias=alias, names=names), imp_tok)  # type: ignore[return-value]

    def _extern_decl(self) -> ExternFuncDecl:
        ext_tok = self._advance()  # extern
        header: str | None = None
        if self._check("STRING"):
            header_tok = self._advance()
            header = header_tok.text
        self._expect("fn", "Expected `fn` in extern declaration",
                     'Example: `extern "math.h" fn sqrt(x: f64) -> f64` or `extern fn func(x: i32) -> i32`')
        name_tok = self._expect("NAME", "Expected function name")
        self._expect("(", "Expected `(`")
        params: list[Param] = []
        variadic = False
        if not self._check(")"):
            while True:
                if self._check("..", "."):  # `...` in lexer comes as `..` + `.`
                    self._advance()
                    if not self._match("."):
                        raise self._error(self.tok, "Variadic marker must be `...` (ellipsis).")
                    variadic = True
                    if not params:
                        raise self._error(self.tok, "Variadic extern function requires at least one fixed parameter.",
                                          "Example: `extern fn printf(fmt: *u8, ...) -> i32`")
                    break
                params.append(self._param())
                if not self._match(","):
                    break
        self._expect(")", "Expected `)`")
        ret = self._type("return") if self._match("->") else None
        local = name_tok.text
        c_symbol = ""
        if self.tok.kind == "NAME" and self.tok.text == "as":
            self._advance()
            local_tok = self._expect("NAME", "Expected Greengold name after `as`",
                                     'Example: `extern "math.h" fn sqrt(x: f64) -> f64 as c_sqrt`.')
            local = local_tok.text
            c_symbol = name_tok.text
        if self._check(":"):
            raise self._error(self.tok, "extern functions cannot have a body; do not write `:` or a block.")
        self._end_stmt()
        decl = self._at(ExternFuncDecl(header, local, params, ret, variadic=variadic, c_symbol=c_symbol), ext_tok)
        return decl  # type: ignore[return-value]

    def _const_decl(self) -> ConstDecl:
        c_tok = self._advance()  # const / static
        name = self._expect("NAME", "Expected constant name")
        type_ref: TypeRef | None = None
        if self._check(":="):
            self._removed_walrus(self.tok)
            self.toks[self.pos] = Token("=", "=", self.tok.line, self.tok.col, 1)
        if self._match("="):
            val = self._expr()
        elif self._match(":"):
            type_ref = self._type("variable")
            self._expect("=", "Expected `=` in constant declaration")
            val = self._expr()
        else:
            raise self._error(self.tok, "Expected `=` or `:` in constant declaration",
                              f"Write `const {name.text} = value` or `const {name.text}: type = value`.")
        self._end_stmt()
        return self._at(ConstDecl(name.text, type_ref, val), c_tok)  # type: ignore[return-value]

    def _type(self, ctx: str) -> TypeRef:
        """Type name: `i32`, `Player`, `[N]T`, `[]T` ... `consume`/`read`/`lend` are forbidden here."""
        if self._check(*PARAM_MODES):
            kw = self.tok
            msg = _REF_MSG[ctx].format(kw=f"{kw.kind} T")
            raise self._error(kw, msg, "Write the type without the keyword.")
        boxed = self.tok.kind == "NAME" and self.tok.text == "Fn" and self._peek().kind == "("
        if ctx == "type argument" and self._check("INT"):  # `Grid[2, 3]`: a value for a constant parameter
            num = self._advance()
            return self._at(TypeRef(str(int(num.text))), num)  # type: ignore[return-value]
        if self._check("fn") or boxed:  # function pointer `fn(A, B) -> R`, or owned closure `Fn(A, B) -> R`
            start = self._advance()
            self._expect("(", "Expected `(` in function type", "Write in the form `fn(i32, i32) -> i32`.")
            ptys: list[TypeRef] = []
            if not self._check(")"):
                ptys.append(self._type(ctx))
                while self._match(","):
                    ptys.append(self._type(ctx))
            self._expect(")", "Expected `)` in function type")
            fret = self._type(ctx) if self._match("->") else None
            word = "Fn" if boxed else "fn"
            name = f"{word}({', '.join(p.name for p in ptys)})" + (f" -> {fret.name}" if fret else "")
            tref = TypeRef(name, is_fn=True, fn_boxed=boxed, fn_params=ptys, fn_ret=fret)
            return self._at(tref, start)  # type: ignore[return-value]
        if self._check("("):  # tuple type: `(A, B)` == `Tuple2[A, B]`
            start = self._advance()
            elems = [self._type(ctx)]
            while self._match(","):
                if self._check(")"):
                    break
                elems.append(self._type(ctx))
            self._expect(")", "Expected `)` in tuple type")
            if not 2 <= len(elems) <= MAX_TUPLE:
                raise self._error(start, f"Tuple types must have 2 to {MAX_TUPLE} elements.",
                                  "Use a struct for larger groups.")
            base = f"Tuple{len(elems)}"
            shown = f"{base}[{', '.join(a.name for a in elems)}]"
            return self._at(TypeRef(shown, base=base, args=elems), start)  # type: ignore[return-value]
        if self._check("*"):  # raw pointer: `*T` / `*mut T`
            start = self._advance()  # *
            is_mut = bool(self.tok.kind == "NAME" and self.tok.text == "mut" and self._match("NAME"))
            elem = self._type(ctx)
            name = f"*mut {elem.name}" if is_mut else f"*{elem.name}"
            return self._at(TypeRef(name, elem=elem, is_ptr=True, ptr_mut=is_mut), start)  # type: ignore[return-value]
        if self._check("["):
            start = self._advance()  # [
            if self._match("]"):
                # Slice: []T
                elem = self._type(ctx)
                tref = TypeRef(f"[]{elem.name}", elem=elem, is_slice=True)
                return self._at(tref, start)
            else:
                # Array: [N]T
                size_expr = self._expr()
                self._expect("]", "Expected `]`")
                elem = self._type(ctx)
                size_str = unparse(size_expr)
                tref = TypeRef(f"[{size_str}]{elem.name}", size_expr=size_expr, elem=elem, is_array=True)
                return self._at(tref, start)
        if self.tok.kind == "NAME" and self.tok.text == "dyn" and self._peek().kind == "NAME":
            start = self._advance()  # `dyn Feature` / `dyn mod.Feature`
            first = self._advance()
            qual, fname = None, first.text
            if self._check(".") and self._peek().kind == "NAME":
                self._advance()
                qual, fname = first.text, self._advance().text
            shown = f"dyn {qual}.{fname}" if qual else f"dyn {fname}"
            return self._at(TypeRef(shown, base=fname, qualifier=qual, is_dyn=True), start)  # type: ignore[return-value]
        tok = self._expect("NAME", "Expected type name")
        qualifier: str | None = None
        if self._check(".") and self._peek().kind == "NAME":
            self._advance()
            member = self._expect("NAME", "Expected type name after `.`")
            qualifier = tok.text
            tok = member
        if tok.text == "Array" and self._check("["):  # `Array[T, N]` == `[N]T`
            self._advance()
            elem = self._type(ctx)
            self._expect(",", "Expected `,` after element type in `Array[T, N]`")
            size_expr = self._expr()
            self._expect("]", "Expected `]`")
            size_str = unparse(size_expr)
            return self._at(TypeRef(f"[{size_str}]{elem.name}", size_expr=size_expr, elem=elem, is_array=True), tok)  # type: ignore[return-value]
        c_base = TYPE_ALIASES.get(tok.text, tok.text)
        if self._check("["):  # generic application: Pair[i32, f64]
            args = self._type_args()
            shown = f"{c_base}[{', '.join(a.name for a in args)}]"
            node = self._at(TypeRef(shown, base=c_base, args=args, qualifier=qualifier), tok)
            return node  # type: ignore[return-value]
        if self._match("in"):
            lo_neg = bool(self._match("-"))
            lo_tok = self._expect("INT", "Expected lower bound integer in range type")
            lo = -int(lo_tok.text) if lo_neg else int(lo_tok.text)
            self._expect("..", "Expected `..` in range type")
            hi_neg = bool(self._match("-"))
            hi_tok = self._expect("INT", "Expected upper bound integer in range type")
            hi = -int(hi_tok.text) if hi_neg else int(hi_tok.text)
            shown = f"{tok.text} in {lo}..{hi}"
            return self._at(TypeRef(shown, range_lo=lo, range_hi=hi, is_bounded=True), tok)  # type: ignore[return-value]
        return self._at(TypeRef(c_base, qualifier=qualifier), tok)  # type: ignore[return-value]

    def _type_args(self) -> list[TypeRef]:
        """`[i32, f64]` — type argument list. Currently on `[`."""
        self._expect("[", "Expected `[`")
        if self._check("]"):
            raise self._error(self.tok, "Type argument list cannot be empty.", "Write in the form `Pair[i32, f64]`.")
        args = [self._type("type argument")]
        while self._match(","):
            args.append(self._type("type argument"))
        self._expect("]", "Expected `]`")
        return args

    def _struct_decl(self) -> StructDecl:
        self._advance()  # struct / union
        name = self._expect("NAME", "Expected struct name")
        type_params = self._type_params() if self._check("[") else []
        bounds = self.bounds if type_params else {}
        self._expect(":", "Expected `:` after struct name", "Write in the form `struct Player:`.")
        self._expect("NEWLINE", "Fields must be written on indented lines after `:`")
        self._expect("INDENT", "Struct fields must be indented with 4 spaces")
        fields: list[FieldDecl] = []
        while not self._check("DEDENT", "EOF"):
            try:
                if self._check("public", "private"):
                    self._visibility_section()
                    continue
                fattrs = self._attr_lines()
                fname = self._expect("NAME", "Expected field name")
                self._expect(":", "Missing field type", "Write in the form `name: type`, e.g. `health: i32`.")
                fmode, ftied, fsoa = "", None, False
                if self._check("read", "lend"):  # reference field: `owner: read Player tied to self`
                    fmode = self._advance().kind
                if self._match("soa"):
                    fsoa = True
                tref = self._type("field")
                if self._match("tied"):
                    ftied = self._tied_target()
                if fmode and ftied is None:
                    self._soft_error(fname, f"Reference field `{fname.text}` requires a `tied to` binding.",
                                     f"`{fname.text}: {fmode} {tref.name} tied to self`.")
                if ftied is not None and not fmode:
                    self._soft_error(fname, "`tied to` can only be used on `read`/`lend` reference fields.")
                self._end_stmt()
                fd = self._at(FieldDecl(fname.text, tref), fname)
                fd.mode, fd.tied_to, fd.is_soa, fd.is_pub = fmode, ftied, fsoa, self._export  # type: ignore[attr-defined]
                fd.attrs = fattrs  # type: ignore[attr-defined]
                fields.append(fd)  # type: ignore[arg-type]
            except ParseError:
                self._sync_stmt()
        self._match("DEDENT")
        if not fields:
            self._soft_error(name, f"Struct `{name.text}` has no fields.",
                             "Add at least one `field: type` line.")
        decl = StructDecl(name.text, fields, type_params=type_params, bounds=bounds)
        decl.line, decl.col, decl.length = name.line, name.col, len(name.text)
        if self.filename is not None:
            decl.filename = self.filename
        return decl

    def _type_params(self) -> list[str]:
        """`[A, B]` — type parameter list (names start with uppercase). Currently on `[`."""
        self._expect("[", "Expected `[`")
        names: list[str] = []
        self.bounds = {}
        while True:
            tok = self._expect("NAME", "Expected type parameter name", "Write in the form `[T]` or `[A, B]`.")
            if not tok.text[0].isupper():
                self._soft_error(tok, f"Type parameter `{tok.text}` must start with an uppercase letter.",
                                 f"Write as `{tok.text[0].upper() + tok.text[1:]}`.")
            names.append(tok.text)
            if self._match(":"):  # `T: Ord + Show`
                bl = []
                while True:
                    b = self._expect("NAME", "Expected feature name", "Write in the form `[T: Ord]` or `[T: Ord + Show]`.")
                    bl.append(self._at(Binding(b.text), b))
                    if not self._match("+"):
                        break
                self.bounds[tok.text] = bl
            if not self._match(","):
                break
        self._expect("]", "Expected `]`")
        return names

    def _enum_decl(self) -> EnumDecl:
        """`enum Name[T]:` + indented variants (`Name`, `Name(type, type)`)."""
        self._advance()  # enum
        name = self._expect("NAME", "Expected enum name")
        type_params = self._type_params() if self._check("[") else []
        bounds = self.bounds if type_params else {}
        self._expect(":", "Expected `:` after enum name", "Write in the form `enum Shape:`.")
        self._expect("NEWLINE", "Variants must be written on indented lines after `:`")
        self._expect("INDENT", "Enum variants must be indented with 4 spaces")
        variants: list[VariantDecl] = []
        while not self._check("DEDENT", "EOF"):
            try:
                if self._check("public", "private"):
                    self._visibility_section()
                    continue
                variants.append(self._variant_decl())
            except ParseError:
                self._sync_stmt()
        self._match("DEDENT")
        if not variants:
            self._soft_error(name, f"Enum `{name.text}` has no variants.",
                             "Add at least one variant, e.g. `Empty` or `Circle(f32)`.")
        decl = EnumDecl(name.text, variants, type_params=type_params, bounds=bounds)
        decl.line, decl.col, decl.length = name.line, name.col, len(name.text)
        if self.filename is not None:
            decl.filename = self.filename
        return decl

    def _variant_decl(self) -> VariantDecl:
        vname = self._expect("NAME", "Expected variant name")
        payload: list[TypeRef] = []
        value: int | None = None
        if self._match("="):  # `Red = 1`: the variant's number (C enums)
            neg = bool(self._match("-"))
            num = self._expect("INT", "Expected an integer after `=`", "Write the variant's number: `Red = 1`.")
            value = -int(num.text) if neg else int(num.text)
            if self._check("("):
                raise self._error(self.tok, "A variant with a number (`A = 1`) cannot carry a payload.",
                                  "Numbers are for plain variants, as in C enums.")
        if self._match("("):
            if self._check(")"):
                raise self._error(self.tok, f"`{vname.text}()` contains empty payload parentheses.",
                                  f"If there is no payload, write `{vname.text}` without parentheses.")
            while True:
                if self._check("NAME") and self._peek().kind == ":":
                    raise self._error(self.tok, "Named variant fields are not supported.",
                                      "Use positional payload only: `Circle(f32)`.")
                payload.append(self._type("payload"))
                if not self._match(","):
                    break
            self._expect(")", "Expected `)`")
        self._end_stmt()
        return self._at(VariantDecl(vname.text, payload, value=value), vname)  # type: ignore[return-value]

    def _enum_number_methods(self, decls: list) -> list:
        """`to_int(self) -> i64` and `from_int(n: i64) -> Optional[E]` for each enum whose variants carry
        nothing (`Red = 1`, or numbered in order like C). A method the file defines itself is kept."""
        out: list = []
        own = {(d.owner, d.name) for d in decls if isinstance(d, FuncDecl) and d.owner}
        for d in decls:
            if not isinstance(d, EnumDecl) or d.type_params or not d.variants or any(v.payload for v in d.variants):
                continue
            numbers, nxt = [], 0
            for v in d.variants:
                n = v.value if v.value is not None else nxt
                numbers.append(n)
                nxt = n + 1
            seen: dict[int, str] = {}
            for v, n in zip(d.variants, numbers):
                if n in seen:
                    self.diags.error(f"`{v.name}` and `{seen[n]}` have the same number {n}.", v.line, v.col,
                                     len(v.name), "Give each variant its own number.", filename=self.filename)
                seen.setdefault(n, v.name)
            lines = [f"impl {d.name}:"]
            if (d.name, "to_int") not in own:
                lines += ["    fn to_int(self) -> i64:", "        match self:"]
                lines += [f"            {v.name}: return {n}" for v, n in zip(d.variants, numbers)]
            if (d.name, "from_int") not in own:
                lines += [f"    fn from_int(n: i64) -> Optional[{d.name}]:", "        match n:"]
                lines += [f"            {n}: return Valid({d.name}.{seen[n]})" for n in dict.fromkeys(numbers)]
                lines += ["            _: return None"]
            if len(lines) == 1:
                continue
            sub_diags = DiagnosticBag()
            made = Parser(tokenize("\n".join(lines) + "\n", sub_diags), sub_diags, filename=self.filename).parse_program()
            for f in made.decls:
                for n in walk(f):
                    n.line, n.col, n.length = d.line, d.col, d.length
                f.synthesized = True  # type: ignore[attr-defined]
                f.is_pub = getattr(d, "is_pub", True)
                out.append(f)
        return out

    def _feature_decl(self) -> FeatureDecl:
        """`feature Name:` + indented `fn name(self: Self, ...) -> T` signatures or default implementations."""
        self._advance()  # feature
        name = self._expect("NAME", "Expected feature name")
        self._expect(":", "Expected `:` after feature name", "Write in the form `feature Shape:`.")
        self._expect("NEWLINE", "Signatures must be written on indented lines after `:`")
        self._expect("INDENT", "Feature signatures must be indented with 4 spaces")
        methods: list[FuncDecl] = []
        while not self._check("DEDENT", "EOF"):
            try:
                if self._check("public", "private"):
                    self._visibility_section()
                    continue
                if not self._check("fn"):
                    raise self._error(self.tok, "Only `fn name(...)` signatures or methods can be written inside a feature.",
                                      "E.g. `fn area(self: Self) -> f64`")
                methods.append(self._func_decl(in_feature=True))
            except ParseError:
                self._sync_stmt()
        self._match("DEDENT")
        if not methods:
            self._soft_error(name, f"Feature `{name.text}` has no signatures.", "Add at least one `fn ...` signature.")
        decl = FeatureDecl(name.text, methods)
        decl.line, decl.col, decl.length = name.line, name.col, len(name.text)
        if self.filename is not None:
            decl.filename = self.filename
        return decl

    def _func_decl(self, sig_only: bool = False, in_feature: bool = False,
                   impl: tuple[str, list[str]] | None = None, owner_qualifier: str | None = None) -> FuncDecl:
        fn_index = self.pos
        self._advance()  # fn
        first = self._expect("NAME", "Expected function name")
        owner, name, header_len = None, first.text, len(first.text)
        type_params: list[str] = []
        owner_params: list[str] = []
        if in_feature and self._check("["):
            raise self._error(self.tok, "Feature methods cannot have their own type parameters.")
        if impl is not None:  # method inside `impl Owner[...]:`
            owner, owner_params = impl
            if self._check("["):
                raise self._error(self.tok, "Methods cannot have their own type parameters.")
        # `fn max[T](...)` or `fn Pair[A, B].swap(...)`? After closing `]`, comes `(` or `.`.
        listed = self._type_params() if (impl is None and not in_feature and self._check("[")) else None
        bounds = self.bounds if listed is not None else {}
        if listed is not None and not self._check("(", "."):
            raise self._error(self.tok, f"Expected `(` after type parameter list (found {self._describe(self.tok)}).",
                              "Generic function: `fn max[T](...)`. For methods, use `impl Type[...]:`.")
        if impl is not None:
            pass
        elif self._match("."):
            second = self._expect("NAME", "Expected method name")
            type_name = f"{first.text}[{', '.join(listed)}]" if listed else first.text
            raise self._error(first, f"Direct method declaration `fn {type_name}.{second.text}` is not supported.",
                              f"Define methods inside an `impl {type_name}:` block instead:\n    impl {type_name}:\n        fn {second.text}(self): ...",
                              fixes=self._impl_move_fix(fn_index, first, second, type_name))
        else:
            type_params = listed or []
        self._expect("(", "Expected `(` for parameter list")
        params: list[Param] = []
        if not self._check(")"):
            while True:
                params.append(self._param())
                if not self._match(","):
                    break
        self._expect(")", "Expected `)`")
        ret_view = False
        ret_lend = False
        ret_tied = None
        ret = None
        if self._match("->"):
            # `-> ref T` / `-> lend T` [`tied to param`]: pointer derived from one parameter.
            nxt = self.toks[self.pos + 1]
            is_ref = self.tok.kind == "NAME" and self.tok.text == "ref"
            is_lend = self.tok.kind == "lend"
            if (is_ref or is_lend) and nxt.kind != ":":
                self._advance()
                ret_view = True
                ret_lend = is_lend
            ret = self._type("return")
            if ret_view and self._match("tied"):
                ret_tied = self._tied_target()
        overflow_mode = None
        if self.tok.kind == "NAME" and self.tok.text == "overflow" and self._peek().kind == ":":
            self._advance()
            self._advance()
            mode = self._expect("NAME", "Expected overflow mode ('wrap' or 'trap')")
            overflow_mode = mode.text
        prev_scopes = self._scopes
        self._scopes = [{p.name for p in params}]
        prev_generic = self._outer_generic
        if owner_params or type_params:
            self._outer_generic = (list(owner_params) + [t for t in type_params if t not in owner_params],
                                   dict(bounds))
        try:
            if in_feature:
                if self._check(":"):
                    body = self._block()
                else:
                    body = []
                    self._end_stmt()
            elif sig_only:
                body = []
                self._end_stmt()
            else:
                body = self._block()
        finally:
            self._scopes = prev_scopes
            self._outer_generic = prev_generic
        if overflow_mode is None:
            for s in body:
                if isinstance(s, OverflowMode):
                    overflow_mode = s.mode
                    break
        decl = FuncDecl(name, owner, params, ret, body, type_params=type_params, owner_params=owner_params,
                        ret_view=ret_view, ret_lend=ret_lend, ret_tied=ret_tied, bounds=bounds,
                        overflow_mode=overflow_mode)
        decl.owner_qualifier = owner_qualifier
        if owner is not None and not sig_only and not in_feature:
            subst_self_func(decl, owner, owner_params, owner_qualifier)
        decl.line, decl.col, decl.length = first.line, first.col, header_len
        if self.filename is not None:
            decl.filename = self.filename
        if not sig_only and not in_feature:
            self._test_target = f"{owner}.{name}" if owner else name
        return decl

    def _unique_test_label(self, base: str) -> str:
        n = self._test_labels.get(base, 0) + 1
        self._test_labels[base] = n
        return base if n == 1 else f"{base}.{n}"

    def _test_block(self) -> FuncDecl:
        """`test:` or `test name:` — a function `gg test` runs and `gg run` does not."""
        start = self.tok
        self._advance()
        explicit = self._advance().text if self._check("NAME") else ""
        prev_scopes = self._scopes
        self._scopes = [set()]
        try:
            body = self._block()
        finally:
            self._scopes = prev_scopes
        self._test_serial += 1
        target = self._test_target
        if explicit:
            base = f"{target}.{explicit}" if target else explicit
        else:
            base = f"{target}.test" if target else "test"
        decl = FuncDecl(f"gg_test_{self._test_serial}", None, [], None, body,
                        is_test=True, test_label=self._unique_test_label(base))
        decl.line, decl.col, decl.length = start.line, start.col, len(start.text)
        if self.filename is not None:
            decl.filename = self.filename
        return decl

    @staticmethod
    def _subst_self(params: list[Param], ret: TypeRef | None, owner: str, owner_params: list[str]) -> None:
        """Inside methods `Self` means the owner type (`Pair[A, B]` for generic owners)."""
        dummy = FuncDecl("", owner, params, ret, [])
        subst_self_func(dummy, owner, owner_params)

    def _param(self) -> Param:
        name = self._expect("NAME", "Expected parameter name")
        if name.text == "self" and self._check(",", ")"):  # bare `self`: type is `Self`
            return self._at(Param("self", self._at(TypeRef("Self"), name), ""), name)  # type: ignore[return-value]
        self._expect(":", "Missing parameter type", "Write in the form `name: type`, e.g. `amount: i32`.")
        # `f: send Fn()`: the argument goes to another thread (contextual word, checked by the compiler).
        send = self.tok.kind == "NAME" and self.tok.text == "send" and self._peek().kind not in (",", ")", "NEWLINE", "=")
        if send:
            self._advance()
        exclusive = bool(self._match("exclusive"))
        mode_tok = self._match(*PARAM_MODES)
        mode = mode_tok.kind if mode_tok else ""
        if exclusive and mode not in ("read", "lend"):
            self._soft_error(name, "`exclusive` can only be used on `read`/`lend` parameters.",
                             "`a: exclusive lend []f32` format.")
        tref = self._type("parameter")
        mode_line = mode_col = mode_length = 0
        if mode_tok is not None:
            mode_line, mode_col = mode_tok.line, mode_tok.col
            if tref.line == mode_tok.line and tref.col > mode_tok.col:
                mode_length = tref.col - mode_tok.col
            else:
                mode_length = mode_tok.length
        tied = None
        if self._match("tied"):
            tied = self._tied_target()
            if not mode or mode == "consume":
                self._soft_error(name, "`tied to` can only be used on `read`/`lend` parameters.")
        p = self._at(Param(name.text, tref, mode, mode_line=mode_line, mode_col=mode_col,
                           mode_length=mode_length), name)
        p.tied_to = tied  # type: ignore[attr-defined]
        p.exclusive = exclusive  # type: ignore[attr-defined]
        p.send = send  # type: ignore[attr-defined]
        return p  # type: ignore[return-value]

    def _tied_target(self) -> str:
        """`tied` consumed: read `to NAME`."""
        to = self._expect("NAME", "Expected `to` after `tied`", "`tied to self` format.")
        if to.text != "to":
            raise self._error(to, "Expected `to` after `tied`.", "`tied to self` format.")
        target = self._expect("NAME", "Expected name after `tied to`", "`tied to self` format.")
        return target.text

    # -- blocks and statements -------------------------------------
    def _block(self) -> list[Stmt]:
        self._block_colon("Expected `:` to start block", "Add `:` at end of line.")
        scope = set(self._pending_bindings)
        self._pending_bindings.clear()
        if not self._check("NEWLINE", "EOF"):  # `if x > 0: return 1`
            return self._inline_body(scope)
        self._expect("NEWLINE", "Block must start on the next line after `:`")
        self._expect("INDENT", "Expected indented block", "Indent lines of the block by 4 spaces.")
        self._scopes.append(scope)
        try:
            return self._stmt_list()
        finally:
            self._scopes.pop()

    _COMPOUND = ("if", "elif", "else", "while", "for", "match", "unsafe", "fn", "struct", "enum", "impl", "test")

    def _inline_body(self, scope: set[str]) -> list[Stmt]:
        """One simple statement after the `:` on the same line: `if x > 0: return 1`, `Leaf(v): return v`."""
        t = self.tok
        if t.kind in self._COMPOUND:
            raise self._error(t, f"`{t.text}` opens a block, so it cannot follow `:` on the same line.",
                              f"Put `{t.text} ...` on the next line, indented by 4 spaces.")
        self._scopes.append(scope)
        try:
            s = self._statement()
        finally:
            self._scopes.pop()
        return s if isinstance(s, list) else [s]

    def _stmt_list(self) -> list[Stmt]:
        """INDENT consumed: reads statements until DEDENT."""
        stmts: list[Stmt] = []
        while not self._check("DEDENT", "EOF"):
            try:
                s = self._statement()
                if isinstance(s, list):  # destructuring expands to several statements
                    stmts.extend(s)
                else:
                    stmts.append(s)
            except ParseError:
                self._sync_stmt()
        self._match("DEDENT")
        return stmts

    # -- desugared forms: destructuring, `if let`, `while let` -------
    def _is_destructure(self) -> bool:
        """`a, b = expr` / `fixed a, b = expr`."""
        i = self.pos
        if self.toks[i].kind in ("fixed", "var"):
            i += 1
        names = 0
        while self.toks[i].kind == "NAME":
            names += 1
            i += 1
            if self.toks[i].kind == ",":
                i += 1
                continue
            break
        return names >= 2 and self.toks[i].kind == "="

    def _destructure(self) -> list[Stmt]:
        start = self.tok
        if self._check("var"):
            self._removed_var()
        fixed = self._match("fixed")
        names = [self._expect("NAME", "Expected variable name")]
        while self._match(","):
            names.append(self._expect("NAME", "Expected variable name"))
        self._expect("=", "Expected `=`")
        value = self._expr()
        self._end_stmt()
        self.tmp_counter += 1
        tmp = f"__tup{self.tmp_counter}"
        out: list[Stmt] = [self._at(VarDecl(tmp, False, None, value), start)]  # type: ignore[list-item]
        for i, n in enumerate(names):
            if n.text == "_":
                continue
            src = self._at(FieldAccess(self._at(Name(tmp), n), f"f{i}"), n)
            decl = self._at(VarDecl(n.text, fixed is None, None, src), n)
            if fixed is not None:
                decl.fixed_at = (fixed.line, fixed.col)  # type: ignore[attr-defined]
            self._scopes[-1].add(n.text)
            out.append(decl)  # type: ignore[arg-type]
        return out

    def _is_let(self) -> bool:
        return (self.tok.kind == "NAME" and self.tok.text == "let"
                and self._peek().kind in ("NAME", "INT", "FLOAT", "CHAR", "STRING", "true", "false", "-"))

    def _let_parts(self) -> tuple[MatchArm, Expr]:
        """After `let`: `Pattern = expr` -> (arm without body, scrutinee)."""
        self._advance()  # let
        self._pat_only = True
        try:
            arm = self._match_arm()
        finally:
            self._pat_only = False
        self._expect("=", "Expected `=` after pattern in `let`", "Write `if let Valid(x) = value:`.")
        return arm, self._expr()

    def _wild_arm(self, start: Token, body: list[Stmt]) -> MatchArm:
        arm = MatchArm(None, None, [], body, False)
        return self._header(arm, start)  # type: ignore[return-value]

    def _if_let(self, start: Token) -> Stmt:
        arm, scrut = self._let_parts()
        self._pending_bindings = {b.name for b in arm.bindings if b.name != "_"}
        arm.body = self._block()
        else_body: list[Stmt] | None = None
        if self._check("elif"):
            raise self._error(self.tok, "`elif` after `if let` is not supported.", "Use `else:` with a nested `if`.")
        if self._check("else"):
            self._advance()
            else_body = self._block()
        self._header(arm, start)
        wild = self._wild_arm(start, else_body if else_body is not None else [self._at(Pass(), start)])  # type: ignore[list-item]
        return self._header(Match(scrut, "", [arm, wild]), start)  # type: ignore[return-value]

    def _while_let(self, start: Token) -> Stmt:
        arm, scrut = self._let_parts()
        self._pending_bindings = {b.name for b in arm.bindings if b.name != "_"}
        arm.body = self._block()
        self._header(arm, start)
        wild = self._wild_arm(start, [self._at(Break(), start)])  # type: ignore[list-item]
        m = self._header(Match(scrut, "", [arm, wild]), start)
        cond = self._at(BoolLit(True), start)
        return self._header(While(cond, [m]), start)  # type: ignore[return-value,list-item]

    def _match_stmt(self, as_expr: bool = False) -> Match:
        """`match [consume|lend] expr:` and indented arms. `as_expr`: arms are `Pattern => value`."""
        start = self._advance()  # match
        mode_tok = self._match("consume", "lend")  # consume: moves payload; lend: mutates in-place
        mode = mode_tok.kind if mode_tok else ""
        scrutinee = self._expr()
        self._block_colon("Expected `:` at end of `match` line", "Write in the form `match value:`.")
        self._expect("NEWLINE", "Arms must start on the next line after `:`")
        self._expect("INDENT", "`match` arms must be indented", "Indent arms by 4 spaces.")
        arms: list[MatchArm] = []
        failed = False
        while not self._check("DEDENT", "EOF"):
            try:
                arms.append(self._match_arm(as_expr))
            except ParseError:
                failed = True  # already reported; no second message about the arms being missing
                self._sync_stmt()
        self._match("DEDENT")
        if not arms and not failed:
            self._soft_error(start, "`match` must contain at least one arm.", "E.g. write `_:` with `pass` underneath.")
        return self._header(Match(scrutinee, mode, arms), start)  # type: ignore[return-value]

    def _match_arm(self, as_expr: bool = False) -> MatchArm:
        """`Variant:`, `Enum.Variant(a, _):` or `_:`."""
        if self.tok.kind in self._SCALAR_START:
            return self._scalar_arm(as_expr)
        first = self._expect("NAME", "Expected arm pattern",
                             "Arm is written in the form `Variant:`, `Variant(name, ...):` or `_:`.")
        qualifier, variant, bindings = None, first.text, []
        has_parens = False
        if self._match("."):
            qualifier = first.text
            variant = self._expect("NAME", "Expected variant name").text
        if variant == "_" and qualifier is None:
            if self._check("("):
                raise self._error(self.tok, "`_` arm cannot take parentheses.", "Write only `_:`.")
            wildcard = True
        else:
            wildcard = False
            if self._match("("):
                has_parens = True
                while True:
                    b = self._expect("NAME", "Expected binding name (or `_`) in pattern",
                                     "Write `Rect(w, h)` or `Rect(_, h)`.")
                    bindings.append(self._at(Binding(b.text), b))
                    if not self._match(","):
                        break
                self._expect(")", "Expected `)`")
        label = "_" if wildcard else (f"{qualifier}.{variant}" if qualifier else variant)
        arm = MatchArm(None if wildcard else variant, qualifier, bindings, [], has_parens)
        if not wildcard and qualifier is None and not has_parens and self._check("if"):
            arm.whole = variant  # `n if n > 3:` names the value, unless `n` is a variant (decided by the checker)
            arm.whole_at = self._at(Binding(variant), first)  # type: ignore[attr-defined]
        return self._arm_rest(first, label, arm, as_expr)

    _SCALAR_START = ("INT", "FLOAT", "CHAR", "STRING", "true", "false", "-")

    def _scalar_atom(self) -> Expr:
        """Literal in a pattern: `5`, `-3`, `'a'`, `"text"`, `true`."""
        t = self.tok
        if t.kind == "-":
            self._advance()
            if self.tok.kind not in ("INT", "FLOAT"):
                raise self._error(self.tok, "Expected a number after `-` in pattern.", "Write e.g. `-1:`.")
            return self._at(Unary("-", self._primary()), t)  # type: ignore[return-value]
        if t.kind not in self._SCALAR_START:
            raise self._error(t, "Expected a literal in `match` pattern.",
                              "Patterns can be numbers, characters, strings, `true`/`false`, ranges or `_`.")
        return self._primary()

    def _scalar_arm(self, as_expr: bool) -> MatchArm:
        """`1:`, `1 | 2:`, `'a'..='z':`, `"quit":`, `true:` (and `=>` form in expression match)."""
        first = self.tok
        pats: list[Node] = []
        while True:
            lo = self._scalar_atom()
            if self._check("..", "..="):
                inclusive = self._advance().kind == "..="
                hi = self._scalar_atom()
                pats.append(self._at(RangePat(lo, hi, inclusive), lo))  # type: ignore[arg-type]
            else:
                pats.append(lo)
            if not self._match("|"):
                break
        label = " | ".join(unparse_pat(p) for p in pats)
        arm = MatchArm(None, None, [], [], False)
        arm.pats = pats
        return self._arm_rest(first, label, arm, as_expr)

    def _arm_rest(self, first: Token, label: str, arm: MatchArm, as_expr: bool) -> MatchArm:
        """Part of arm after the pattern: `:` + body block, or `=> value`."""
        if self._pat_only:
            return arm
        arm_scope = {b.name for b in arm.bindings if b.name != "_"} | ({arm.whole} if arm.whole else set())
        if self._match("if"):
            self._scopes.append(arm_scope)
            try:
                arm.guard = self._expr()
            finally:
                self._scopes.pop()
            label += " if ..."
        if as_expr:
            self._expect("=>", f"Expected `=>` in `{label}` arm",
                         f"In expression match, arm is written as `{label} => value`.")
            self._scopes.append(arm_scope)
            try:
                value = self._expr()
            finally:
                self._scopes.pop()
            arm.body = [self._at(Yield(value), first)]  # type: ignore[list-item]
            self._header(arm, first)
            self._end_stmt()
            return arm
        self._expect(":", f"Expected `:` in `{label}` arm", f"Write `{label}:`.")
        if not self._check("NEWLINE", "EOF"):  # `Leaf(v): return v`
            self._header(arm, first)
            arm.body = self._inline_body(arm_scope)
            return arm
        self._expect("NEWLINE", "Arm body must start on the next line after `:`")
        self._header(arm, first)
        if not self._check("INDENT"):
            # Soft error so as not to swallow next arm.
            self._soft_error(first, f"Arm `{label}` body is empty.",
                             "Arm body must contain at least one statement; write `pass` to leave empty.")
            return arm
        self._advance()  # INDENT
        self._scopes.append(arm_scope)
        try:
            arm.body = self._stmt_list()
        finally:
            self._scopes.pop()
        return arm

    def _end_stmt(self) -> None:
        if self._check("NEWLINE"):
            self._advance()
        elif self.pos > 0 and self.toks[self.pos - 1].kind == "DEDENT":
            return  # indented `match` expression closed the line itself
        elif not self._check("EOF"):
            raise self._error(self.tok, f"Expected end of line (found {self._describe(self.tok)}).",
                              "Only one statement per line.")

    def _statement(self) -> Stmt:
        t = self.tok
        k = t.kind
        if k == "INDENT":
            raise self._error(t, "Unexpected indentation.",
                              "Remove indentation if preceding line does not end with `:`.",
                              fixes=self._unexpected_indent_fixes())
        if k in ("var", "fixed", "NAME"):
            self._fix_walrus_in_line()
        if k in ("var", "fixed", "NAME") and self._is_destructure():
            return self._destructure()  # type: ignore[return-value]
        # `wrapping:` and `overflow: wrap` stand alone on the line; `wrapping: i32 = 0` declares a variable.
        if k == "NAME" and t.text == "wrapping" and self._peek().kind == ":" and self._peek(2).kind == "NEWLINE":
            self._advance()
            body = self._block()
            node = Wrapping(body)
            return self._header(node, t)  # type: ignore[return-value]
        if k == "NAME" and t.text == "overflow" and self._peek().kind == ":" and self._peek(3).kind in ("NEWLINE", "EOF"):
            self._advance()
            self._advance()  # ':'
            mode = self._expect("NAME", "Expected overflow mode ('wrap' or 'trap')")
            node = self._at(OverflowMode(mode.text), t)
            self._end_stmt()
            return node  # type: ignore[return-value]
        if k in ("var", "fixed") or (k == "NAME" and (self._peek().kind == ":" or (self._peek().kind == "=" and not self._in_scope(t.text)))):
            return self._var_decl()
        if k == "NAME" and t.text == "let" and (self._peek().kind == "NAME") \
                and (self._peek(2).kind in ("=", ":") or (self._peek().text == "mut" and self._peek(2).kind == "NAME")):
            return self._let_stmt()
        if k == "if":
            return self._if()
        if k == "unsafe":  # `unsafe:` block: single-branch If with condition `true`
            self._advance()
            body = self._block()
            cond = self._at(BoolLit(True), t)
            node = If([self._at(Branch(cond, body), t)], None, unsafe=True)  # type: ignore[arg-type]
            return self._header(node, t)  # type: ignore[return-value]
        if k == "while":
            self._advance()
            if self._is_let():
                return self._while_let(t)
            cond = self._expr()
            stmt = While(cond, self._block())
            return self._header(stmt, t)  # type: ignore[return-value]
        if k == "for":
            return self._for()
        if k == "return":
            self._advance()
            value = None if self._check("NEWLINE", "EOF") else self._expr()
            node = self._at(Return(value), t)
            self._end_stmt()
            return node  # type: ignore[return-value]
        if k in ("break", "continue"):
            self._advance()
            node = Break() if k == "break" else Continue()
            self._at(node, t)
            self._end_stmt()
            return node
        if k == "match":
            return self._match_stmt()
        if k == "defer":
            self._advance()
            inner = self._simple_stmt()
            ok = isinstance(inner, Assign) or (isinstance(inner, ExprStmt) and not isinstance(inner.expr, Try))
            if not ok:
                raise self._error(t, "`defer` defers a call or assignment.",
                                  "Write in the form `defer cleanup(x)`; `?` cannot be deferred.")
            return self._at(Defer(inner), t)  # type: ignore[return-value]
        if k == "pass":
            self._advance()
            node = self._at(Pass(), t)
            self._end_stmt()
            return node  # type: ignore[return-value]
        if k == "require" or (k == "NAME" and t.text == "require"):
            self._advance()
            cond = self._expr()
            node = self._at(Require(cond), t)
            self._end_stmt()
            return node  # type: ignore[return-value]
        return self._simple_stmt()

    def _header(self, node: Node, start: Token) -> Node:
        """Anchors location of statements with bodies to their keyword."""
        node.line, node.col, node.length = start.line, start.col, len(start.text)
        return node

    def _var_decl(self) -> VarDecl:
        if self._check("var"):
            self._removed_var()
        start = self.tok
        fixed = self._match("fixed")
        if not self._check("NAME"):
            raise self._error(self.tok, f"Expected variable name after `fixed` (found {self._describe(self.tok)}).",
                              "Write in the form `fixed x = 5`.")
        name = self._advance()
        type_ref = None
        ref_mode = ""
        op_at = (self.tok.line, self.tok.col)
        if self._check(":="):
            self._removed_walrus(self.tok)
            self.toks[self.pos] = Token("=", "=", self.tok.line, self.tok.col, 1)
        if not self._match("="):
            self._expect(":", "Expected `=` or `: type =`")
            if self._check("read", "lend"):  # `r: read Player = hero`
                ref_mode = self._advance().kind
            type_ref = self._type("variable")
            self._expect("=", "Variable must be given an initial value",
                         f"Write in the form `{name.text}: {type_ref.name} = value`.")
        value = self._expr()
        node = self._at(VarDecl(name.text, fixed is None, type_ref, value, ref_mode=ref_mode), start)
        if type_ref is None:
            node.op_at = op_at  # type: ignore[attr-defined]
        node.name_at = (name.line, name.col)  # type: ignore[attr-defined]
        if fixed is not None:
            node.fixed_at = (fixed.line, fixed.col)  # type: ignore[attr-defined]
        node.is_soa = isinstance(value, SoaExpr)  # type: ignore[attr-defined]
        self._scopes[-1].add(name.text)
        self._end_stmt()
        return node  # type: ignore[return-value]

    def _if(self) -> If:
        start = self._advance()  # if
        if self._is_let():
            return self._if_let(start)  # type: ignore[return-value]
        branches: list[Branch] = []
        cond = self._expr()
        branches.append(self._header(Branch(cond, self._block()), start))  # type: ignore[arg-type]
        while self._check("elif"):
            kw = self._advance()
            cond = self._expr()
            branches.append(self._header(Branch(cond, self._block()), kw))  # type: ignore[arg-type]
        else_body = None
        if self._check("else"):
            if self._peek().kind == "if":
                if_tok = self._peek()
                raise self._error(
                    self.tok, "`else if` does not exist; use `elif`.", "Write `elif` instead of `else if`.",
                    fixes=[Fix(
                        "Replace `else if` with `elif`",
                        "safe",
                        [Edit(self.tok.line, self.tok.col, if_tok.line, if_tok.col + len(if_tok.text), "elif",
                              self.filename)],
                    )])
            self._advance()
            else_body = self._block()
        return self._header(If(branches, else_body), start)  # type: ignore[return-value]

    def _if_expr(self) -> Expr:
        """Expression-style `if`: value of each arm is an expression; `else` is required."""
        start = self._advance()  # if
        branches: list[Branch] = []
        kw = start
        while True:
            cond = self._expr()
            self._expect("then", "Expected `then` after condition in `if` expression",
                         "Write in the form `if cond then a else b`.")
            first = self.tok
            value = self._expr()
            branches.append(self._header(Branch(cond, [self._at(Yield(value), first)]), kw))  # type: ignore[arg-type,list-item]
            if self._check("elif"):
                kw = self._advance()
                continue
            break
        if not self._check("else"):
            raise self._error(self.tok, "`if` expression cannot produce a value without `else`.",
                              "Write in the form `if cond then a else b`.")
        self._advance()
        first = self.tok
        value = self._expr()
        node = self._header(If(branches, [self._at(Yield(value), first)]), start)  # type: ignore[list-item]
        return self._at(BlockExpr(node), start)  # type: ignore[arg-type,return-value]

    def _for(self) -> Stmt:
        start = self._advance()  # for
        # `for x in xs:` lends the element when the body changes `x` (the type checker decides).
        mutable = False
        if self._check("var"):
            self._removed_var()
        var = self._expect("NAME", "Expected loop variable name")
        index_var = None
        if self._check(","):  # `for i, x in xs:` -> i: index, x: element
            self._advance()
            elem = self._expect("NAME", "Expected element variable name after `,`")
            index_var, var = var, elem
        loop_vars = {var.text} | ({index_var.text} if index_var is not None else set())
        self._expect("in", "Expected `in`",
                     "Write in the form `for i in 0..n:`, `for i in n:` or `for x in a:`.")
        if self.tok.kind == "NAME" and self.tok.text == "range":
            self._advance()
            if index_var is not None:
                raise self._error(var, "Range loops cannot use an index variable.",
                                  "Write `for i in range n:`.")
            has_paren = self._check("(")
            if has_paren:
                self._advance()
            first = self._expr()
            if has_paren:
                self._expect(")", "Expected `)` after range argument")
            if self._check("..", "..="):
                inclusive = self._advance().kind == "..="
                last = self._expr()
                step = None
                if self.tok.kind == "NAME" and self.tok.text == "step":
                    self._advance()
                    step = self._expr()
                self._pending_bindings = loop_vars
                node = For(var.text, first, last, inclusive, self._block())
                node.step = step
                return self._header(node, start)  # type: ignore[return-value]
            else:
                zero = self._at(IntLit(0), start)
                step = None
                if self.tok.kind == "NAME" and self.tok.text == "step":
                    self._advance()
                    step = self._expr()
                self._pending_bindings = loop_vars
                node = For(var.text, zero, first, False, self._block())
                node.step = step
                return self._header(node, start)  # type: ignore[return-value]
        first = self._expr()
        if self._check("..", "..="):
            if index_var is not None:
                raise self._error(var, "Range loops cannot use an index variable.",
                                  "Write `for i in a..b:`.")
            inclusive = self._advance().kind == "..="
            last = self._expr()
            step = None
            if self.tok.kind == "NAME" and self.tok.text == "step":
                self._advance()
                step = self._expr()
            self._pending_bindings = loop_vars
            node = For(var.text, first, last, inclusive, self._block())
            node.step = step
            return self._header(node, start)  # type: ignore[return-value]
        else:
            self._pending_bindings = loop_vars
            node2 = ForIn(var.text, first, self._block(), mutable=mutable,
                          index_var=index_var.text if index_var is not None else None)
            return self._header(node2, start)  # type: ignore[return-value]

    def _simple_stmt(self) -> Stmt:
        start = self.tok
        expr = self._expr()
        if self._check(*ASSIGN_OPS):
            op = self._advance()
            if not isinstance(expr, (Name, FieldAccess, IndexAccess, Call, MethodCall)):  # a call: `-> lend T`
                raise self._error(expr, "Left side of assignment must be a variable or field.",
                                  "Write `x = 5` or `p.x = 5`.")
            value = self._expr()
            node = self._at(Assign(expr, op.text, value), start)
            node.op_at = (op.line, op.col)  # type: ignore[attr-defined]
        else:
            if not isinstance(expr, (Call, MethodCall, Try)):
                word, fixes = self._keyword_typo_fix(expr)
                raise self._error(expr, "This expression does not perform any action.",
                                  f"Did you mean `{word}`?" if word else
                                  "Assign the result to a variable or call a function.", fixes=fixes)
            node = self._at(ExprStmt(expr), start)
        self._end_stmt()
        return node  # type: ignore[return-value]

    # -- expressions (precedence climbing) -------------------------
    def _expr(self, min_prec: int = 0) -> Expr:
        t = self.tok
        if t.kind == "await":  # `await task` is `std.tasks.wait(task)`
            self._advance()
            self.uses_tasks = True
            operand = self._expr(11)
            left = self._at(MethodCall(self._at(Name("_gg_tasks"), t), "wait", [operand]), t)  # type: ignore[assignment]
        elif t.kind == "not":
            self._advance()
            operand = self._expr(4)
            left: Expr = self._at(Unary("not", operand), t)  # type: ignore[assignment]
        elif t.kind in ("-", "~"):
            self._advance()
            operand = self._expr(11)
            left = self._at(Unary(t.kind, operand), t)  # type: ignore[assignment]
        else:
            left = self._postfix()
        while True:
            t = self.tok
            op_kind = t.text if (t.kind == "NAME" and t.text in WORD_BINARY_OPS) else t.kind
            prec = BINARY_PREC.get(op_kind)
            if prec is None or prec < min_prec:
                break
            op = self._advance()
            op_name = op.text if op.kind == "NAME" else op.kind
            if op_name in COMPARE_OPS and isinstance(left, Binary) and left.op in COMPARE_OPS:
                raise self._error(op, "Chained comparison operations are not supported.",
                                  "Write `a < b and b < c`.")
            right = self._expr(prec + 1)  # left-associative
            left = self._at(Binary(op_name, left, right), left)  # type: ignore[assignment]
        return left

    def _postfix(self) -> Expr:
        expr = self._primary()
        while self._check(".", "[", "?") or (
                self._check("(") and isinstance(expr, (Call, MethodCall, IndexAccess, Apply))
                and self.tok.line == self.toks[self.pos - 1].line):
            if self._check("("):  # `make_adder(5)(1)`: call the function value a call returned
                expr = self._at(Apply(expr, self._args()), expr)  # type: ignore[assignment]
            elif self._match("?"):  # postfix `?`: only valid as whole expression (type checker decides)
                expr = self._at(Try(expr), expr)  # type: ignore[assignment]
            elif self._check(".") and self._peek().kind in ("INT", "FLOAT"):  # tuple field `t.0` / `t.0.1`
                self._advance()
                num = self._advance()
                for part in num.text.split("."):
                    if not part.isdigit():
                        raise self._error(num, "Invalid tuple index.")
                    expr = self._at(FieldAccess(expr, f"f{int(part)}"), expr)  # type: ignore[assignment]
            elif self._match("."):
                name = self._expect("NAME", "Expected field or method name after `.`")
                if isinstance(expr, Name) and self._check("["):
                    close, _comma = self._bracket_scan(self.pos)
                    after = self.toks[close + 1].kind if close is not None else None
                    if after == "(":  # `math.max[i32](...)`, not an index
                        call = self._qualified_generic_call(expr, name)
                        if call is not None:
                            expr = call
                            continue
                if self._check("("):
                    args = self._args()
                    expr = self._at(MethodCall(expr, name.text, args), expr)  # type: ignore[assignment]
                else:
                    expr = self._at(FieldAccess(expr, name.text), expr)  # type: ignore[assignment]
                expr.member_at = (name.line, name.col)  # type: ignore[attr-defined]  # where a rename fix goes
            else:
                open_pos = self.pos
                expr = self._index_suffix(expr)
                if isinstance(expr, IndexAccess) and isinstance(expr.obj, FieldAccess) and self._check("."):
                    end_pos = self.pos  # `mod.Pair[i32].new()`: the brackets may be type arguments
                    self.pos = open_pos
                    expr.type_alt = self._probe(self._type_args)
                    self.pos = end_pos
        return expr

    def _index_suffix(self, obj: Expr) -> Expr:
        """`[i]` (IndexAccess) or `[a..b]` (SliceExpr). Currently on `[`."""
        self._advance()  # [
        if self._check("..", "..="):
            range_tok = self._advance()
            inclusive = range_tok.kind == "..="
            end = None
            if not self._check("]"):
                end = self._expr()
            self._expect("]", "Expected `]`")
            return self._at(SliceExpr(obj, None, end, inclusive), obj)  # type: ignore[return-value]
        first = self._expr()
        if self._check("..", "..="):
            range_tok = self._advance()
            inclusive = range_tok.kind == "..="
            end = None
            if not self._check("]"):
                end = self._expr()
            self._expect("]", "Expected `]`")
            return self._at(SliceExpr(obj, first, end, inclusive), obj)  # type: ignore[return-value]
        self._expect("]", "Expected `]`")
        return self._at(IndexAccess(obj, first), obj)  # type: ignore[return-value]

    # -- bracketed name: index or type application? ----------------
    def _attempt(self, fn):
        """Tries `fn`; on ParseError rewinds position and diagnostics and returns None."""
        pos, n = self.pos, len(self.diags.items)
        try:
            return fn()
        except ParseError:
            self.pos = pos
            del self.diags.items[n:]
            return None

    def _probe(self, fn):
        """Tries `fn` and (regardless of outcome) rewinds position and diagnostics. Only for "can it be parsed?" check."""
        pos, n = self.pos, len(self.diags.items)
        try:
            return fn()
        except ParseError:
            return None
        finally:
            self.pos = pos
            del self.diags.items[n:]

    def _bracket_scan(self, open_pos: int) -> tuple[int | None, bool]:
        """Token index of matching `]` from `[` and whether there is a top-level comma."""
        depth, comma = 0, False
        for i in range(open_pos, len(self.toks)):
            k = self.toks[i].kind
            if k in ("(", "[", "{"):
                depth += 1
            elif k in (")", "]", "}"):
                depth -= 1
                if depth == 0:
                    return (i if k == "]" else None), comma
            elif k == "," and depth == 1:
                comma = True
            elif k in ("NEWLINE", "EOF"):
                break
        return None, comma

    def _bracketed_name(self, name: Token) -> Expr:
        """`name[...]`: indexing (`a[i]`, `a[1..3]`), generic call (`max[i64](5, 2)`), generic struct
        value (`Pair[i32, f64]{...}`) or type application (`Optional[i32].None`).

        The decision belongs to type checking (is name a variable, or type/generic function?); parser
        only checks syntax: comma list can never be an index, before `(`/`{` can never be an index.
        """
        open_pos = self.pos
        close, has_comma = self._bracket_scan(open_pos)
        after = self.toks[close + 1].kind if close is not None else None
        one_number = close == open_pos + 2 and self.toks[open_pos + 1].kind == "INT"
        if not has_comma and after == "(" and (self._probe(self._type_args) is None
                                               or one_number and self._in_scope(name.text)):
            return self._index_suffix(self._at(Name(name.text), name))  # `handlers[0](x)`: index, then call
        if has_comma or after in ("(", "{"):
            targs = self._type_args()
            if self._check("("):
                return self._at(Call(name.text, self._args(), type_args=targs), name)  # type: ignore[return-value]
            if self._check("{"):
                return self._struct_lit(name, targs)
            return self._at(TypeApp(name.text, targs), name)  # type: ignore[return-value]
        base = self._at(Name(name.text), name)
        node = self._attempt(lambda: self._index_suffix(base))
        if node is None:
            targs = self._probe(self._type_args)  # `Optional[[3]i32].None`: single arg that cannot be read as expr
            if targs is None:
                return self._index_suffix(base)  # report real syntax error
            return self._at(TypeApp(name.text, self._type_args()), name)  # type: ignore[return-value]
        if after == "." and isinstance(node, IndexAccess):
            end_pos = self.pos
            self.pos = open_pos
            node.type_alt = self._probe(self._type_args)  # could be `Optional[i32].None`
            self.pos = end_pos
        return node

    def _primary(self) -> Expr:
        t = self.tok
        k = t.kind
        if k == "INT":
            self._advance()
            return self._at(IntLit(int(t.text)), t)  # type: ignore[return-value]
        if k == "FLOAT":
            self._advance()
            return self._at(FloatLit(t.text), t)  # type: ignore[return-value]
        if k == "STRING":
            self._advance()
            return self._at(StrLit(t.text), t)  # type: ignore[return-value]
        if k == "FSTRING":
            self._advance()
            return self._parse_fstring(t)  # type: ignore[return-value]
        if k == "CHAR":
            self._advance()
            val = int(t.text)
            return self._at(CharLit(val, chr(val)), t)  # type: ignore[return-value]
        if k in ("true", "false"):
            self._advance()
            return self._at(BoolLit(k == "true"), t)  # type: ignore[return-value]
        if k == "NAME":
            self._advance()
            if t.text in NUMERIC_CAST_TYPES and self._check("("):
                self._advance()  # (
                arg = self._expr()
                self._expect(")", "Expected `)`")
                target_ty = TYPE_ALIASES.get(t.text, t.text)
                return self._at(Cast(target_ty, arg), t)  # type: ignore[return-value]
            if self._check("["):
                return self._bracketed_name(t)
            if self._check("("):
                args = self._args()
                return self._at(Call(t.text, args), t)  # type: ignore[return-value]
            if self._check("{"):
                return self._struct_lit(t)
            if self._check(".") and self._peek().kind == "NAME":
                lit = self._qualified_struct_lit(t)
                if lit is not None:
                    return lit
            return self._at(Name(t.text), t)  # type: ignore[return-value]
        if k == "[":
            start_tok = self._advance()  # [
            if self._check("]"):
                self._advance()
                return self._at(ArrayLit([]), start_tok)  # type: ignore[return-value]
            first = self._expr()
            if self._match(";"):
                count = self._expr()
                self._expect("]", "Expected `]`")
                return self._at(ArrayRepeatLit(first, count), start_tok)  # type: ignore[return-value]
            elements = [first]
            while self._match(","):
                if self._check("]"):
                    break
                elements.append(self._expr())
            self._expect("]", "Expected `]`")
            return self._at(ArrayLit(elements), start_tok)  # type: ignore[return-value]
        if k == "(":
            self._advance()
            inner = self._expr()
            if self._check(","):  # tuple literal `(a, b)`
                elems = [inner]
                while self._match(","):
                    if self._check(")"):
                        break
                    elems.append(self._expr())
                self._expect(")", "Expected `)`")
                if not 2 <= len(elems) <= MAX_TUPLE:
                    raise self._error(t, f"Tuples must have 2 to {MAX_TUPLE} elements.")
                inits = [self._at(FieldInit(f"f{i}", v), v) for i, v in enumerate(elems)]  # type: ignore[arg-type]
                lit = StructLit(f"Tuple{len(elems)}", inits)
                lit.is_tuple = True  # type: ignore[attr-defined]
                return self._at(lit, t)  # type: ignore[return-value]
            self._expect(")", "Expected `)`")
            return inner
        if k == "fn":  # lambda: `fn(x: i32) -> i32 => x + 1` (no captures; lifted to a top-level function)
            return self._lambda()
        if k == "if":  # `if c then a elif d then b else e`
            return self._if_expr()
        if k == "match":
            m = self._match_stmt(as_expr=True)
            return self._at(BlockExpr(m), t)  # type: ignore[return-value]
        if k == "copy":  # `copy x`: explicit copy
            self._advance()
            target = self._expr(8)
            return self._at(CopyExpr(target), t)  # type: ignore[return-value]
        if k in ("read", "lend"):  # `read place` / `lend place`: borrow without taking ownership
            self._advance()
            target = self._expr(8)
            return self._at(BorrowExpr(k, target), t)  # type: ignore[return-value]
        if k == "trust":  # `trust items[i]`: unchecked indexing in release mode
            self._advance()
            target = self._postfix()
            if not isinstance(target, IndexAccess):
                raise self._error(t, "`trust` can only be applied to an indexing expression, e.g. `trust items[i]`.")
            target.trusted = True
            return target
        if k == "soa":  # `soa Array[T, N]` / `soa [N]T`: array in SoA memory layout
            self._advance()
            tref = self._type("variable")
            if self._check("("):
                self._advance()
                self._expect(")", "Expected `)`")
            return self._at(SoaExpr(tref), t)  # type: ignore[return-value]
        if k == "consume":
            raise self._error(t, "`consume` can only be used in a parameter definition.",
                              "Ownership moves when the parameter is `consume`, or when a move type is assigned.")
        raise self._error(t, f"Expected expression (found {self._describe(t)}).")

    def _parse_fstring(self, tok: Token) -> FormatStr:
        from .lexer import tokenize
        text = tok.text
        parts: list[Expr] = []
        buf: list[str] = []
        i = 0
        n = len(text)
        while i < n:
            if text[i:i + 2] == "{{":
                buf.append("{")
                i += 2
                continue
            if text[i:i + 2] == "}}":
                buf.append("}")
                i += 2
                continue
            if text[i] == "{":
                if buf:
                    parts.append(self._at(StrLit("".join(buf)), tok))
                    buf = []
                j = i + 1
                brace_depth = 1
                while j < n and brace_depth > 0:
                    if text[j] == '"':
                        j += 1
                        while j < n and text[j] != '"':
                            if text[j] == "\\" and j + 1 < n:
                                j += 2
                            else:
                                j += 1
                        if j < n:
                            j += 1
                        continue
                    if text[j] == "'":
                        j += 1
                        while j < n and text[j] != "'":
                            if text[j] == "\\" and j + 1 < n:
                                j += 2
                            else:
                                j += 1
                        if j < n:
                            j += 1
                        continue
                    if text[j] == "{":
                        brace_depth += 1
                    elif text[j] == "}":
                        brace_depth -= 1
                    j += 1
                if brace_depth != 0:
                    self.diags.error("Unclosed `{` in formatted string literal.", tok.line, tok.col + i,
                                     hint="Add matching `}`.")
                    break
                expr_src = text[i + 1:j - 1].strip()
                spec = None
                colon = _top_level_colon(expr_src)
                if colon is not None:  # `{x:>8.2}`: the format spec follows the first top-level `:`
                    expr_src, spec = expr_src[:colon].strip(), expr_src[colon + 1:]
                if not expr_src:
                    self.diags.error("Empty expression in formatted string literal `{}`.", tok.line, tok.col + i,
                                     hint="Provide an expression to format, e.g. `{var}`.")
                else:
                    inner_diags = DiagnosticBag()
                    inner_tokens = tokenize(expr_src, inner_diags)
                    for d in inner_diags.items:
                        self.diags.error(d.message, tok.line, tok.col + i + d.col, d.length, d.hint)
                    if not inner_diags.has_errors():
                        inner_parser = Parser(inner_tokens, self.diags, filename=self.filename)
                        expr_node = inner_parser._expr()
                        _adjust_fstring_pos(expr_node, tok.line, tok.col + i + 1)
                        if not inner_parser._check("NEWLINE", "EOF"):
                            extra = inner_parser.tok
                            self.diags.error(f"Unexpected {inner_parser._describe(extra)} in `{{...}}` of a formatted string.",
                                             tok.line, tok.col + i + extra.col, max(len(extra.text), 1),
                                             hint="Write one expression, then optionally `:` and a format such as "
                                                  "`{x:.2}`, `{n:>6}`, or `{n:x}`.")
                        if spec is not None:
                            expr_node.fmt_spec = spec  # type: ignore[attr-defined]  # checked by TypeChecker
                        parts.append(expr_node)
                i = j
                continue
            buf.append(text[i])
            i += 1
        if buf:
            parts.append(self._at(StrLit("".join(buf)), tok))
        if not parts:
            parts.append(self._at(StrLit(""), tok))
        return self._at(FormatStr(parts), tok)

    def _lambda(self) -> Expr:
        """`fn(a: T, b: U) -> R => expr` (or `fn(a: T) => call()` without result). Lifted to a hidden function."""
        import zlib
        start = self._advance()  # fn
        self._expect("(", "Expected `(` after `fn` in lambda")
        params: list[Param] = []
        if not self._check(")"):
            while True:
                params.append(self._param())
                if not self._match(","):
                    break
        self._expect(")", "Expected `)`")
        ret = self._type("return") if self._match("->") else None
        self._expect("=>", "Expected `=>` in lambda", "Write in the form `fn(x: i32) -> i32 => x + 1`.")
        body_expr = self._expr()
        if ret is not None:
            body: list[Stmt] = [self._at(Return(body_expr), body_expr)]  # type: ignore[list-item]
        else:
            if not isinstance(body_expr, (Call, MethodCall)):
                raise self._error(body_expr, "A lambda without `->` must be a call (no result).",
                                  "Add a result type: `fn(x: i32) -> i32 => x + 1`.")
            body = [self._at(ExprStmt(body_expr), body_expr)]  # type: ignore[list-item]
        self.lambda_counter += 1
        tag = zlib.crc32((self.filename or "").encode()) & 0xFFFF
        name = f"__lambda_{tag:x}_{self.lambda_counter}"
        decl = FuncDecl(name, None, params, ret, body)
        decl.line, decl.col, decl.length = start.line, start.col, 2
        if self.filename is not None:
            decl.filename = self.filename
        decl.is_lambda = True  # type: ignore[attr-defined]
        outer, outer_bounds = self._outer_generic
        if outer:  # inside `fn f[T]`: one lambda per instance of `f`, with `T` bound the same way
            decl.type_params = list(outer)
            decl.bounds = {k: list(v) for k, v in outer_bounds.items()}
        self.lifted.append(decl)
        return self._at(Name(name), start)  # type: ignore[return-value]

    def _args(self) -> list[Expr]:
        """`(` arg, arg ... `)`."""
        self._expect("(", "Expected `(`")
        args: list[Expr] = []
        if not self._check(")"):
            while True:
                args.append(self._arg())
                if not self._match(","):
                    break
        self._expect(")", "Expected `)`", "Separate arguments with commas and close with `)`.")
        return args

    def _arg(self) -> Expr:
        return self._expr()

    def _qualified_generic_call(self, mod: Name, name: Token) -> Call | None:
        """`math.max[i32](1, 2)`. Rewinds when `[...]` is an index, not a type argument list before `(`."""
        pos, n = self.pos, len(self.diags.items)
        try:
            targs = self._type_args()
            if not self._check("("):
                raise self._error(self.tok, "Expected `(` after type arguments.")
            args = self._args()
        except ParseError:
            self.pos = pos
            del self.diags.items[n:]
            return None
        return self._at(Call(name.text, args, type_args=targs, qualifier=mod.name), mod)  # type: ignore[return-value]

    def _qualified_struct_lit(self, mod: Token) -> StructLit | None:
        """`combat.Hero { ... }` or `combat.Hero[i32] { ... }`. Rewinds if this is not a struct literal."""
        pos, n = self.pos, len(self.diags.items)
        self._advance()  # .
        member = self._expect("NAME", "Expected type name after `.`")
        type_args: list[TypeRef] | None = None
        if self._check("["):
            close, _comma = self._bracket_scan(self.pos)
            after = self.toks[close + 1].kind if close is not None else None
            if after != "{":  # `obj.field[i]` is an index, not `Mod.Type[T] { }`
                self.pos = pos
                del self.diags.items[n:]
                return None
            type_args = self._type_args()
        if not self._check("{"):
            self.pos = pos
            del self.diags.items[n:]
            return None
        lit = self._struct_lit(member, type_args)
        lit.qualifier = mod.text
        lit.line, lit.col = mod.line, mod.col
        return lit

    def _struct_lit(self, name: Token, type_args: list[TypeRef] | None = None) -> StructLit:
        """`Player{ x: 1.0, y: 2.0 }` — fields separated by commas or newlines.

        Since Lexer does not produce NEWLINE inside `{}`, "separation by newline"
        is detected when next field begins with `name:`.
        """
        self._expect("{", "Expected `{`")
        inits: list[FieldInit] = []
        while not self._check("}"):
            fname = self._expect("NAME", "Expected field name",
                                 "Write in the form `Type{ field: value, ... }`.")
            self._expect(":", "Expected `:` after field name")
            value = self._expr()
            inits.append(self._at(FieldInit(fname.text, value), fname))  # type: ignore[arg-type]
            if not self._match(","):
                if not self._check("}") and not (self._check("NAME") and self._peek().kind == ":"):
                    raise self._error(self.tok, f"Expected `,` or `}}` (found {self._describe(self.tok)}).")
        self._expect("}", "Expected `}`")
        return self._at(StructLit(name.text, inits, type_args=type_args or []), name)  # type: ignore[return-value]


def _top_level_colon(src: str) -> int | None:
    """Index of the first `:` outside brackets and quotes in an f-string `{...}` (None if there is none)."""
    depth, quote = 0, None
    i = 0
    while i < len(src):
        c = src[i]
        if quote:
            if c == "\\":
                i += 1
            elif c == quote:
                quote = None
        elif c in "\"'":
            quote = c
        elif c in "([{":
            depth += 1
        elif c in ")]}":
            depth -= 1
        elif c == ":" and depth == 0:
            return i
        i += 1
    return None


def _relocate(made: Node, origin: Node) -> None:
    """Gives code the compiler wrote for `origin` (an `async fn` wrapper) the position of `origin`, so a
    diagnostic in it points at the declaration."""
    for n in walk(made):
        n.line, n.col = origin.line, origin.col
        if hasattr(n, "length"):
            n.length = getattr(origin, "length", 0)
        if getattr(origin, "filename", None) is not None and hasattr(n, "filename"):
            n.filename = origin.filename


def _adjust_fstring_pos(node: Node, base_line: int, base_col: int) -> None:
    if hasattr(node, "line") and hasattr(node, "col"):
        if node.line == 1:
            node.line = base_line
            node.col = base_col + node.col
        else:
            node.line = base_line + node.line - 1
    for field_name in getattr(node, "__dataclass_fields__", {}):
        val = getattr(node, field_name, None)
        if isinstance(val, Node):
            _adjust_fstring_pos(val, base_line, base_col)
        elif isinstance(val, list):
            for item in val:
                if isinstance(item, Node):
                    _adjust_fstring_pos(item, base_line, base_col)


def parse(tokens: list[Token], diags: DiagnosticBag, filename: str | None = None) -> Program:
    """Generates AST from list of tokens; writes errors to `diags`."""
    return Parser(tokens, diags, filename=filename).parse_program()

