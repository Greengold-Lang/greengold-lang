"""Canonical source layout for `gg fmt`.

Indentation is four spaces per block. A line after `:` is one level deeper.
`else` and `elif` line up with their `if`. Indent inside `()`, `[]`, and `{}`
is four spaces past the line that opened the bracket. The result is idempotent:
formatting it again changes nothing. Strings, including multiline strings, are
left character for character.
"""
from __future__ import annotations

from dataclasses import dataclass

from .diagnostics import Edit, Fix

INDENT = 4


@dataclass
class Decision:
    """How one physical line should look. `indent is None` means keep `text` unchanged."""
    indent: int | None
    text: str
    visual: int
    lead: int
    unambiguous: bool


class Layout:
    """Walks a file in order and chooses the indent of each line."""

    def __init__(self) -> None:
        self.frames: list[tuple[int, str]] = [(0, "")]
        self.pending: str | None = None
        self.depth = 0
        self.in_multi = False
        self.cont = 0

    def feed(self, line: str) -> Decision:
        line = line.rstrip("\r")
        if self.in_multi:
            end = _close_multi(line, 0)
            if end is None:
                return Decision(None, line, 0, 0, False)
            self.in_multi = False
            info = _scan(line[end:], 0)
            self.depth = info.depth
            if info.opens:
                self.pending = info.word or "block"
            return Decision(None, line, 0, 0, False)

        stripped = line.rstrip(" \t")
        lead, visual = _lead(stripped)
        body = stripped[lead:]
        if body == "":
            return Decision(0, "", visual, lead, False)

        depth_before = self.depth
        info = _scan(body, self.depth)
        if info.enter_multi:
            self.in_multi = True
        self.depth = info.depth

        indent, unambiguous = self._place(info.word, info.comment, depth_before, visual)
        if depth_before == 0 and self.depth > 0:
            self.cont = indent + INDENT
        if info.opens and not info.comment:
            self.pending = info.word or "block"
        return Decision(indent, body, visual, lead, unambiguous and not info.comment)

    def _place(self, word: str, comment: bool, depth_before: int, visual: int) -> tuple[int, bool]:
        if depth_before > 0:
            return self.cont, False
        if word in ("else", "elif") and not comment:
            if self.pending in ("if", "elif"):
                self.pending = None
                return self.frames[-1][0], True
            # The `if` this `else` belongs to is the open `if` block whose header is nearest to the
            # `else` as written; an inner `if` that ended earlier does not take it.
            heads = [k for k in range(1, len(self.frames)) if self.frames[k][1] in ("if", "elif")]
            if heads:
                k = min(heads, key=lambda k: (abs(visual - (self.frames[k][0] - INDENT)), -k))
                del self.frames[k:]
            return self.frames[-1][0], True
        if self.pending is not None and not comment:
            indent = self.frames[-1][0] + INDENT
            self.frames.append((indent, self.pending))
            self.pending = None
            return indent, True
        if comment:  # a comment keeps the open level nearest to where it is written
            levels = [frame for frame, _opener in self.frames]
            if self.pending is not None:
                levels.append(self.frames[-1][0] + INDENT)
            return min(levels, key=lambda level: (abs(visual - level), -level)), False
        options = [frame for frame, _opener in self.frames]
        best = min(options, key=lambda level: (abs(visual - level), -level))
        while len(self.frames) > 1 and self.frames[-1][0] > best:
            self.frames.pop()
        distance = abs(visual - best)
        unique = sum(1 for level in options if abs(visual - level) == distance) == 1
        return best, unique


def format_source(text: str) -> str:
    """Return the canonical form of `text`. `format_source` of the result is itself."""
    text = text.lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n")
    layout = Layout()
    out: list[str] = []
    blank = 0
    for line in text.split("\n"):
        decision = layout.feed(line)
        if decision.indent is None:
            blank = 0
            out.append(decision.text)
            continue
        if decision.text == "":
            blank += 1
            if blank > 2:
                continue
            out.append("")
            continue
        blank = 0
        out.append((" " * decision.indent) + decision.text)
    while out and out[-1] == "":
        out.pop()
    return "\n".join(out) + "\n"


def indent_fix(line: int, lead_chars: int, spaces: int) -> Fix:
    """Replace the leading whitespace of one line with exactly `spaces` spaces."""
    return Fix(
        f"Indent with {spaces} spaces",
        "safe",
        [Edit(line, 1, line, lead_chars + 1, " " * spaces)],
    )


@dataclass
class _Scan:
    depth: int
    word: str
    opens: bool
    comment: bool
    enter_multi: bool


def _lead(line: str) -> tuple[int, int]:
    chars = 0
    visual = 0
    for ch in line:
        if ch == " ":
            chars += 1
            visual += 1
        elif ch == "\t":
            chars += 1
            visual += INDENT
        else:
            break
    return chars, visual


def _close_multi(line: str, start: int) -> int | None:
    j = start
    while j < len(line):
        if line[j] == "\\" and j + 1 < len(line):
            j += 2
            continue
        if line[j:j + 3] == '"""':
            return j + 3
        j += 1
    return None


def _skip_quotes(line: str, i: int) -> int:
    """`i` points at the opening quote. Return the index after the closer, or len(line)."""
    j = i + 1
    while j < len(line):
        if line[j] == "\\" and j + 1 < len(line):
            j += 2
            continue
        if line[j] == '"':
            return j + 1
        j += 1
    return len(line)


def _skip_char(line: str, i: int) -> int:
    j = i + 1
    while j < len(line):
        if line[j] == "\\" and j + 1 < len(line):
            j += 2
            continue
        if line[j] == "'":
            return j + 1
        j += 1
    return len(line)


def _scan(body: str, depth: int) -> _Scan:
    i = 0
    n = len(body)
    word = ""
    seen_word = False
    last = ""
    comment = body.startswith("#")
    enter_multi = False
    while i < n:
        c = body[i]
        if c == "#":
            break
        if c in " \t":
            i += 1
            continue
        if body[i:i + 3] == '"""' or (c in "f$" and i + 3 < n and body[i + 1:i + 4] == '"""'):
            start = i + 3 if body[i:i + 3] == '"""' else i + 4
            end = _close_multi(body, start)
            if end is None:
                enter_multi = True
                last = ""
                break
            i = end
            last = '"'
            seen_word = True
            continue
        if c in "f$" and i + 1 < n and body[i + 1] == '"':
            i = _skip_quotes(body, i + 1)
            last = '"'
            seen_word = True
            continue
        if c == '"':
            i = _skip_quotes(body, i)
            last = '"'
            seen_word = True
            continue
        if c == "'":
            i = _skip_char(body, i)
            last = "'"
            seen_word = True
            continue
        if c in "([{":
            depth += 1
            last = c
            seen_word = True
            i += 1
            continue
        if c in ")]}":
            depth = max(0, depth - 1)
            last = c
            seen_word = True
            i += 1
            continue
        if c.isascii() and (c.isalpha() or c == "_"):
            j = i + 1
            while j < n and body[j].isascii() and (body[j].isalnum() or body[j] == "_"):
                j += 1
            if not seen_word and depth == 0:
                word = body[i:j]
            seen_word = True
            last = body[j - 1]
            i = j
            continue
        last = c
        seen_word = True
        i += 1
    opens = depth == 0 and not enter_multi and last == ":"
    return _Scan(depth, word, opens, comment, enter_multi)
