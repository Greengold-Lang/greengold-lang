"""Lexer: converts source text to list of tokens (including INDENT/DEDENT/NEWLINE).

Token kinds (`kind`):
  * NAME, INT, FLOAT, STRING  -> lexical classes
  * NEWLINE, INDENT, DEDENT, EOF -> structural tokens
  * keywords and operators -> kind is the text itself ("fn", ":=", "+" ...)

Newlines and indentation are ignored inside `()` and `{}`.
"""
from __future__ import annotations

from dataclasses import dataclass

from .diagnostics import DiagnosticBag, Edit, Fix
from .fmt import Layout, indent_fix

KEYWORDS = {
    "fn", "struct", "if", "elif", "else", "while", "for", "in", "return",
    # `var` is removed (bindings are mutable by default); it stays reserved so the parser can explain that.
    "break", "continue", "var", "fixed", "const", "and", "or", "not", "public", "private",
    "true", "false", "extern", "pass", "match", "enum", "import", "then", "defer", "feature",
    # Ownership/reference system (consume/read/lend system)
    "consume", "read", "lend",
    # Compile time, memory layout and copying
    "comptime", "copy", "soa", "exclusive", "hot", "trust",
    # Lifetime binding ("tied to Name"); `to` is contextual (remains NAME)
    "tied",
    # FFI: raw pointer operations can only be performed in `unsafe:` block
    "unsafe",
    # Tasks: `async fn` returns a task; `await task` waits for its result (std.tasks)
    "async", "await",
}

THREE_CHAR_OPS = {"..=", "<<=", ">>="}
TWO_CHAR_OPS = {
    ":=", "==", "!=", "<=", ">=", "+=", "-=", "*=", "/=", "%=",
    "&=", "|=", "^=", "->", "..", "<<", ">>", "=>",
}
ONE_CHAR_OPS = set("+-*/%<>=:,.(){}&|^~[];?@")

STRING_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "\\": "\\", '"': '"', "'": "'"}
CHAR_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "\\": "\\", '"': '"', "'": "'", "0": "\0"}
INDENT_WIDTH = 4


@dataclass(frozen=True)
class Token:
    """A single token. `line` and `col` start at 1."""
    kind: str
    text: str
    line: int
    col: int
    length: int = 1


class Lexer:
    def __init__(self, source: str, diags: DiagnosticBag) -> None:
        self.source = source
        self.diags = diags
        self.tokens: list[Token] = []
        self.indents = [0]
        self.layout = Layout()
        self._layout_fix: list[Fix] | None = None
        # Open brackets: (character, line, col)
        self.brackets: list[tuple[str, int, int]] = []
        self.multiline_str: dict | None = None
        # Open `#[ ... ]#` block comment: nesting depth and where the outermost one started.
        self.block_depth = 0
        self.block_start = (1, 1)

    # -- block comments ------------------------------------------
    def _skip_block_comment(self, line: str, i: int, lineno: int) -> int:
        """Scan a block comment body from `i`; return the index after the closing `]#`, or len(line)
        when it stays open (`self.block_depth` stays above 0)."""
        n = len(line)
        while i < n:
            if line[i:i + 2] == "#[":
                self.block_depth += 1
                i += 2
            elif line[i:i + 2] == "]#":
                self.block_depth -= 1
                i += 2
                if self.block_depth == 0:
                    return i
            else:
                i += 1
        return n

    # -- helpers -------------------------------------------------
    def _emit(self, kind: str, text: str, line: int, col: int, length: int | None = None) -> None:
        self.tokens.append(Token(kind, text, line, col, len(text) if length is None else length))

    def _error(self, msg: str, line: int, col: int, length: int = 1, hint: str | None = None,
               fixes: list[Fix] | None = None) -> None:
        self.diags.error(msg, line, col, length, hint, fixes=fixes)

    # -- main loop ---------------------------------------------------
    def run(self) -> list[Token]:
        lines = self.source.split("\n")
        for lineno, raw in enumerate(lines, 1):
            self._lex_line(lineno, raw.rstrip("\r"))
        end_line = len(lines)
        if self.multiline_str is not None:
            self._error("Unterminated multiline string literal.",
                        self.multiline_str["start_line"], self.multiline_str["start_col"],
                        hint='Add closing `"""`.')
        if self.block_depth > 0:
            self._error("Unterminated block comment.", *self.block_start, 2,
                        hint="Add closing `]#`.")
        for ch, line, col in self.brackets:
            self._error(f"`{ch}` opened but never closed.", line, col,
                        hint="Add the matching closing bracket.")
        if self.tokens and self.tokens[-1].kind != "NEWLINE":
            self._emit("NEWLINE", "", end_line, len(lines[-1]) + 1, 0)
        while len(self.indents) > 1:
            self.indents.pop()
            self._emit("DEDENT", "", end_line, 1, 0)
        self._emit("EOF", "", end_line, 1, 0)
        return self.tokens

    def _lex_line(self, lineno: int, line: str) -> None:
        n = len(line)
        i = 0
        emitted = 0
        decision = self.layout.feed(line)
        self._layout_fix = None
        if (decision.indent is not None and decision.unambiguous
                and decision.indent != decision.visual):
            self._layout_fix = [indent_fix(lineno, decision.lead, decision.indent)]
        elif decision.indent is not None and decision.indent != decision.visual and decision.text \
                and not decision.text.startswith("#"):
            # Two block levels are equally close (`  print(x)` between 0 and 4). Offer both; the compiler
            # verifies which one makes the file correct.
            other = 2 * decision.visual - decision.indent
            levels = [decision.indent] + ([other] if other >= 0 and other % INDENT_WIDTH == 0 else [])
            self._layout_fix = []
            for level in sorted(levels, reverse=True):
                fix = indent_fix(lineno, decision.lead, level)
                fix.applicability = "likely"
                fix.alternative = True
                self._layout_fix.append(fix)

        if self.multiline_str is not None:
            i = self._continue_multiline_string(lineno, line)
            if self.multiline_str is not None:
                return  # Still inside multiline string
            emitted += 1

        if self.block_depth > 0:
            i = self._skip_block_comment(line, 0, lineno)
            if self.block_depth > 0:
                return  # Still inside block comment
            if line[i:].strip(" \t") == "" or line[i:].lstrip(" \t").startswith("#"):
                return
            if not self.brackets and self.multiline_str is None:
                self._handle_indent(len(line) - len(line.lstrip(" ")), lineno)

        if not self.brackets and self.multiline_str is None and i == 0:
            # Line leading indentation
            width = 0
            saw_tab = False
            while i < n and line[i] in " \t":
                if line[i] == "\t":
                    if not saw_tab:
                        self._error(
                            "Tab characters are not allowed.", lineno, i + 1,
                            hint=f"Use {INDENT_WIDTH} spaces for indentation.",
                            fixes=[Fix(
                                "Replace this tab with 4 spaces",
                                "safe",
                                [Edit(lineno, i + 1, lineno, i + 2, " " * INDENT_WIDTH)],
                            )])
                        saw_tab = True
                    width += INDENT_WIDTH
                else:
                    width += 1
                i += 1
            if line[i:i + 2] == "#[":
                self.block_start = (lineno, i + 1)
                i = self._skip_block_comment(line, i, lineno)
                rest = line[i:].lstrip(" \t")
                if self.block_depth > 0 or rest == "" or rest.startswith("#"):
                    return  # comment only
                self._handle_indent(width, lineno)
            elif i >= n or line[i] == "#":
                return  # empty line or comment only
            else:
                self._handle_indent(width, lineno)

        while i < n:
            c = line[i]
            col = i + 1
            if c == " ":
                i += 1
            elif c == "\t":
                self._error("Tab characters are not allowed.", lineno, col,
                            hint=f"Use {INDENT_WIDTH} spaces for indentation and spacing.")
                i += 1
            elif c == "#" and line[i + 1:i + 2] == "[":
                self.block_start = (lineno, col)
                i = self._skip_block_comment(line, i, lineno)
                if self.block_depth > 0:
                    break  # block comment continues on the next lines
            elif c == "#":
                break
            elif c == "/" and line[i + 1:i + 2] == "/":
                self._error("// is not a comment, use # for comments.", lineno, col, 2,
                            hint="Write `# text` instead of `// text`.",
                            fixes=[Fix("Replace `//` with `#`", "safe", [Edit(lineno, col, lineno, col + 2, "#")])])
                break
            # Multiline format string: f"""...""" or $"""..."""
            elif (c in ('f', '$') and line[i + 1:i + 4] == '"""'):
                i = self._start_multiline_string(line, i + 4, lineno, col, is_format=True)
                emitted += 1
                if self.multiline_str is not None:
                    return
            # Multiline string: """..."""
            elif line[i:i + 3] == '"""':
                i = self._start_multiline_string(line, i + 3, lineno, col, is_format=False)
                emitted += 1
                if self.multiline_str is not None:
                    return
            # Single-line format string: f"..." or $"..."
            elif c in ('f', '$') and i + 1 < n and line[i + 1] == '"':
                i = self._format_string(line, i + 1, lineno, col)
                emitted += 1
            elif c.isdigit() and c.isascii():
                i = self._number(line, i, lineno)
                emitted += 1
            elif c.isascii() and (c.isalpha() or c == "_"):
                j = i
                while j < n and line[j].isascii() and (line[j].isalnum() or line[j] == "_"):
                    j += 1
                word = line[i:j]
                self._emit(word if word in KEYWORDS else "NAME", word, lineno, col)
                i = j
                emitted += 1
            elif c == '"':
                i = self._string(line, i, lineno)
                emitted += 1
            elif c == "'":
                i = self._char(line, i, lineno)
                emitted += 1
            else:
                i = self._operator(line, i, lineno)
                emitted += 1

        if emitted and not self.brackets and self.multiline_str is None:
            self._emit("NEWLINE", "", lineno, n + 1, 0)

    # -- indentation -------------------------------------------------
    def _take_indent_fix(self) -> list[Fix] | None:
        fix = self._layout_fix
        self._layout_fix = None
        return fix

    def _handle_indent(self, width: int, lineno: int) -> None:
        reported = False
        if width % INDENT_WIDTH != 0:
            self._error(f"Indentation must be a multiple of {INDENT_WIDTH} spaces (currently {width} spaces).",
                        lineno, 1, max(width, 1), hint=f"Use {INDENT_WIDTH}-space indentation.",
                        fixes=self._take_indent_fix())
            reported = True
        current = self.indents[-1]
        if width > current:
            if width - current != INDENT_WIDTH:
                self._error(f"Indentation must increase by {INDENT_WIDTH} spaces at a time.",
                            lineno, 1, max(width, 1), fixes=self._take_indent_fix())
                reported = True
            self.indents.append(width)
            self._emit("INDENT", "", lineno, 1, 0)
        elif width < current:
            while self.indents[-1] > width:
                self.indents.pop()
                self._emit("DEDENT", "", lineno, 1, 0)
            if self.indents[-1] != width:
                self._error("Indentation does not match any outer block.", lineno, 1, max(width, 1),
                            fixes=self._take_indent_fix())
                reported = True
                self.indents.append(width)
        elif self._layout_fix is not None and not reported:
            # The line stayed at the current column, but a block was opened above it.
            self._error(f"Indentation must increase by {INDENT_WIDTH} spaces at a time.",
                        lineno, 1, max(width, 1), hint=f"Use {INDENT_WIDTH}-space indentation.",
                        fixes=self._take_indent_fix())

    # -- lexical classes -------------------------------------------
    def _number(self, line: str, i: int, lineno: int) -> int:
        n = len(line)
        j = i
        # 0x / 0X hex literal
        if j + 1 < n and line[j] == "0" and line[j + 1] in "xX":
            j += 2
            start_digits = j
            while j < n and ((line[j].isascii() and line[j].isalnum()) or line[j] == "_"):
                if line[j] != "_" and line[j] not in "0123456789abcdefABCDEF":
                    break
                j += 1
            clean = line[start_digits:j].replace("_", "")
            if not clean:
                self._error(f"Invalid hexadecimal number: `{line[i:j]}`.", lineno, i + 1, j - i)
                return j
            if j < n and (line[j].isalpha() or line[j] == "_"):
                k = j
                while k < n and (line[k].isalnum() or line[k] == "_"):
                    k += 1
                self._error(f"Invalid number: `{line[i:k]}`.", lineno, i + 1, k - i)
                return k
            val = int(clean, 16)
            self._emit("INT", str(val), lineno, i + 1, j - i)
            return j

        # 0b / 0B binary literal
        if j + 1 < n and line[j] == "0" and line[j + 1] in "bB":
            j += 2
            start_digits = j
            while j < n and (line[j] in "01_"):
                j += 1
            clean = line[start_digits:j].replace("_", "")
            if not clean:
                self._error(f"Invalid binary number: `{line[i:j]}`.", lineno, i + 1, j - i)
                return j
            if j < n and (line[j].isalpha() or line[j] == "_"):
                k = j
                while k < n and (line[k].isalnum() or line[k] == "_"):
                    k += 1
                self._error(f"Invalid number: `{line[i:k]}`.", lineno, i + 1, k - i)
                return k
            val = int(clean, 2)
            self._emit("INT", str(val), lineno, i + 1, j - i)
            return j

        # Standard decimal number or float (can contain underscores)
        while j < n and line[j].isascii() and (line[j].isdigit() or line[j] == "_"):
            j += 1
        kind = "INT"
        # Do not confuse `1..n` or `1..=n` range with float: if there is a dot after the dot, it is a range!
        if j + 1 < n and line[j] == "." and line[j + 1] != "." and line[j + 1].isascii() and (line[j + 1].isdigit()):
            j += 1
            while j < n and line[j].isascii() and (line[j].isdigit() or line[j] == "_"):
                j += 1
            kind = "FLOAT"
        # `1e9`, `2.5e-3`: an exponent makes a float
        if j < n and line[j] in "eE":
            k = j + 1
            if k < n and line[k] in "+-":
                k += 1
            if k < n and line[k].isascii() and line[k].isdigit():
                j = k
                while j < n and line[j].isascii() and (line[j].isdigit() or line[j] == "_"):
                    j += 1
                kind = "FLOAT"

        if j < n and (line[j].isalpha() or line[j] == "_"):
            k = j
            while k < n and (line[k].isalnum() or line[k] == "_"):
                k += 1
            self._error(f"Invalid number: `{line[i:k]}`.", lineno, i + 1, k - i)
            return k

        clean = line[i:j].replace("_", "")
        if kind == "INT":
            val = int(clean, 10)
            self._emit(kind, str(val), lineno, i + 1, j - i)
        else:
            self._emit(kind, clean, lineno, i + 1, j - i)
        return j

    def _string(self, line: str, i: int, lineno: int) -> int:
        n = len(line)
        j = i + 1
        buf: list[str] = []
        closed = False
        while j < n:
            ch = line[j]
            if ch == '"':
                closed = True
                break
            if ch == "\\":
                j += 1
                if j >= n:
                    break
                esc = line[j]
                if esc == "0":
                    self._error("`\\0` escape sequence can only be used in char literals.", lineno, j, 2,
                                hint="`\\0` cannot be used in strings.")
                elif esc in STRING_ESCAPES:
                    buf.append(STRING_ESCAPES[esc])
                else:
                    self._error(f"Unknown escape sequence: `\\{esc}`.", lineno, j, 2,
                                hint="Valid escapes: \\n \\t \\r \\\\ \\\" \\'")
                j += 1
                continue
            if ch == "\t":
                self._error("Tab characters are not allowed (write `\\t` in string).", lineno, j + 1)
                j += 1
                continue
            buf.append(ch)
            j += 1
        if not closed:
            self._error("Unterminated String literal.", lineno, i + 1, n - i,
                        hint='Add closing `"` before end of line.')
            return n
        self._emit("STRING", "".join(buf), lineno, i + 1, j - i + 1)
        return j + 1

    def _start_multiline_string(self, line: str, i: int, lineno: int, start_col: int, is_format: bool) -> int:
        n = len(line)
        buf: list[str] = []
        j = i
        while j < n:
            if line[j:j + 3] == '"""':
                kind = "FSTRING" if is_format else "STRING"
                self._emit(kind, "".join(buf), lineno, start_col, (j + 3) - start_col + 1)
                return j + 3
            if line[j] == "\\":
                if j + 1 < n:
                    esc = line[j + 1]
                    if line[j:j + 2] == '\\"':
                        buf.append('"')
                        j += 2
                        continue
                    if line[j:j + 2] == '\\\\':
                        buf.append('\\')
                        j += 2
                        continue
                    if esc in STRING_ESCAPES:
                        buf.append(STRING_ESCAPES[esc])
                        j += 2
                        continue
                    buf.append("\\")
                    buf.append(esc)
                    j += 2
                    continue
                else:
                    self.multiline_str = {
                        "is_format": is_format,
                        "start_line": lineno,
                        "start_col": start_col,
                        "buf": buf,
                        "suppress_nl": True,
                    }
                    return n
            if line[j] == "\t":
                buf.append(" " * INDENT_WIDTH)
                j += 1
                continue
            buf.append(line[j])
            j += 1
        buf.append("\n")
        self.multiline_str = {
            "is_format": is_format,
            "start_line": lineno,
            "start_col": start_col,
            "buf": buf,
            "suppress_nl": False,
        }
        return n

    def _continue_multiline_string(self, lineno: int, line: str) -> int:
        assert self.multiline_str is not None
        state = self.multiline_str
        buf = state["buf"]
        is_format = state["is_format"]
        start_line = state["start_line"]
        start_col = state["start_col"]
        n = len(line)
        j = 0
        while j < n:
            if line[j:j + 3] == '"""':
                kind = "FSTRING" if is_format else "STRING"
                self._emit(kind, "".join(buf), start_line, start_col)
                self.multiline_str = None
                return j + 3
            if line[j] == "\\":
                if j + 1 < n:
                    esc = line[j + 1]
                    if line[j:j + 2] == '\\"':
                        buf.append('"')
                        j += 2
                        continue
                    if line[j:j + 2] == '\\\\':
                        buf.append('\\')
                        j += 2
                        continue
                    if esc in STRING_ESCAPES:
                        buf.append(STRING_ESCAPES[esc])
                        j += 2
                        continue
                    buf.append("\\")
                    buf.append(esc)
                    j += 2
                    continue
                else:
                    state["suppress_nl"] = True
                    return n
            if line[j] == "\t":
                buf.append(" " * INDENT_WIDTH)
                j += 1
                continue
            buf.append(line[j])
            j += 1
        if not state.get("suppress_nl", False):
            buf.append("\n")
        state["suppress_nl"] = False
        return n

    def _format_string(self, line: str, i: int, lineno: int, start_col: int) -> int:
        n = len(line)
        j = i + 1
        buf: list[str] = []
        brace_depth = 0
        closed = False
        while j < n:
            ch = line[j]
            if ch == '"' and brace_depth == 0:
                closed = True
                break
            if ch == "{" and line[j:j + 2] == "{{":
                buf.append("{{")
                j += 2
                continue
            if ch == "}" and line[j:j + 2] == "}}":
                buf.append("}}")
                j += 2
                continue
            if ch == "{":
                brace_depth += 1
                buf.append(ch)
                j += 1
                continue
            if ch == "}":
                if brace_depth > 0:
                    brace_depth -= 1
                buf.append(ch)
                j += 1
                continue
            if ch == "\\":
                j += 1
                if j >= n:
                    break
                esc = line[j]
                if esc == '"':
                    buf.append('"')
                elif esc == "\\":
                    buf.append("\\")
                elif esc in STRING_ESCAPES:
                    buf.append(STRING_ESCAPES[esc])
                else:
                    buf.append("\\")
                    buf.append(esc)
                j += 1
                continue
            if ch == "\t":
                self._error("Tab characters are not allowed (write `\\t` in string).", lineno, j + 1)
                j += 1
                continue
            buf.append(ch)
            j += 1
        if not closed:
            self._error("Unterminated format string literal.", lineno, start_col, n - start_col + 1,
                        hint='Add closing `"` before end of line.')
            return n
        self._emit("FSTRING", "".join(buf), lineno, start_col, j - start_col + 1)
        return j + 1


    def _char(self, line: str, i: int, lineno: int) -> int:
        n = len(line)
        j = i + 1
        buf: list[str] = []
        closed = False
        while j < n:
            ch = line[j]
            if ch == "'":
                closed = True
                break
            if ch == "\\":
                j += 1
                if j >= n:
                    break
                esc = line[j]
                if esc in CHAR_ESCAPES:
                    buf.append(CHAR_ESCAPES[esc])
                else:
                    self._error(f"Unknown escape sequence: `\\{esc}`.", lineno, j, 2,
                                hint="Valid escapes: \\n \\t \\r \\\\ \\\" \\' \\0")
                j += 1
                continue
            if ch == "\t":
                self._error("Tab characters are not allowed (write `\\t` in char literal).", lineno, j + 1)
                j += 1
                continue
            buf.append(ch)
            j += 1
        if not closed:
            self._error("Unterminated char literal.", lineno, i + 1, n - i,
                        hint="Add closing `'` before end of line.")
            return n
        content = "".join(buf)
        encoded = content.encode("utf-8")
        if len(encoded) == 0:
            self._error("Empty char literal.", lineno, i + 1, j - i + 1,
                        hint="Char literal must contain a single character, e.g. `'A'`.")
        elif len(encoded) > 1:
            if len(content) == 1:
                self._error("Char literal cannot contain multi-byte UTF-8 character.", lineno, i + 1, j - i + 1,
                            hint="Char literal must be single-byte (ASCII).")
            else:
                self._error("Char literal can only contain a single character.", lineno, i + 1, j - i + 1,
                            hint="Use string `\"...\"` for multiple characters.")
        else:
            val = encoded[0]
            self._emit("CHAR", str(val), lineno, i + 1, j - i + 1)
        return j + 1

    def _foreign(self, line: str, i: int, size: int, lineno: int, word: str, message: str) -> None:
        """Report `line[i:i+size]` as syntax from another language; the fix writes `word` instead."""
        before = "" if i == 0 or line[i - 1] in " ([" else " "
        after_ch = line[i + size:i + size + 1]
        after = "" if after_ch in ("", " ", ")", "]") else " "
        text = before + word + after
        self._error(message, lineno, i + 1, size, hint=f"Write `{word.strip()}`.",
                    fixes=[Fix(f"Replace `{line[i:i + size]}` with `{word.strip()}`", "safe",
                               [Edit(lineno, i + 1, lineno, i + size + 1, text)])])

    def _rest_is_empty(self, line: str, j: int) -> bool:
        rest = line[j:].strip()
        return rest == "" or rest.startswith("#")

    def _operator(self, line: str, i: int, lineno: int) -> int:
        col = i + 1
        two = line[i:i + 2]
        # Habits from C, Java, JavaScript, and Rust. Each is reported with a fix, and the lexer reads the
        # Greengold word in its place so the rest of the file is still checked.
        if two in ("&&", "||"):
            word = "and" if two == "&&" else "or"
            self._foreign(line, i, 2, lineno, word, f"`{two}` is not Greengold syntax; write `{word}`.")
            self._emit(word, word, lineno, col, 2)
            return i + 2
        if line[i] == "!" and two != "!=":
            self._foreign(line, i, 1, lineno, "not", "`!` is not Greengold syntax; write `not`.")
            self._emit("not", "not", lineno, col, 1)
            return i + 1
        if two in ("++", "--") and not self.brackets and i > 0 and (line[i - 1].isalnum() or line[i - 1] in "_)]") \
                and self._rest_is_empty(line, i + 2):
            op = two[0] + "="
            self._error(f"`{two}` is not Greengold syntax; write `{op} 1`.", lineno, col, 2,
                        hint=f"Write `x {op} 1`.",
                        fixes=[Fix(f"Replace `{two}` with `{op} 1`", "safe",
                                   [Edit(lineno, col, lineno, col + 2, f" {op} 1")])])
            self._emit(op, op, lineno, col, 2)
            self._emit("INT", "1", lineno, col + 1, 1)
            return i + 2
        if line[i] == ";" and not self.brackets:
            if self._rest_is_empty(line, i + 1):
                start = i
                while start > 0 and line[start - 1] == " ":
                    start -= 1
                self._error("`;` is not Greengold syntax; a line ends a statement.", lineno, col, 1,
                            hint="Delete the `;`.",
                            fixes=[Fix("Delete `;`", "safe", [Edit(lineno, start + 1, lineno, col + 1, "")])])
                return i + 1
            end = i + 1
            while end < len(line) and line[end] == " ":
                end += 1
            lead = len(line) - len(line.lstrip(" "))
            self._error("`;` is not Greengold syntax; write one statement per line.", lineno, col, 1,
                        hint="Put the next statement on its own line.",
                        fixes=[Fix("Put the next statement on its own line", "safe",
                                   [Edit(lineno, col, lineno, end + 1, "\n" + " " * lead)])])
            self._emit("NEWLINE", "", lineno, col, 0)
            return end
        for size, table in ((3, THREE_CHAR_OPS), (2, TWO_CHAR_OPS), (1, ONE_CHAR_OPS)):
            chunk = line[i:i + size]
            if len(chunk) == size and chunk in table:
                if chunk in "([{":
                    self.brackets.append((chunk, lineno, col))
                elif chunk in ")]}":
                    self._close_bracket(chunk, lineno, col)
                self._emit(chunk, chunk, lineno, col)
                return i + size
        self._error(f"Unrecognized character: `{line[i]}`.", lineno, col)
        return i + 1

    def _close_bracket(self, ch: str, lineno: int, col: int) -> None:
        expected = {")": "(", "}": "{", "]": "["}[ch]
        if not self.brackets:
            self._error(f"Extra `{ch}`: no matching open bracket.", lineno, col)
        elif self.brackets[-1][0] != expected:
            self._error(f"`{ch}` closes wrong bracket.", lineno, col)
            self.brackets.pop()
        else:
            self.brackets.pop()


def tokenize(source: str, diags: DiagnosticBag) -> list[Token]:
    """Converts source to list of tokens; writes errors to `diags`."""
    return Lexer(source, diags).run()
