"""Diagnostics. The objects in a `DiagnosticBag` are the source of truth.

Human text (`render`) and `gg check --json` are both produced from those objects.
Color is a presentation layer on the human text: `color=False` (the default) is
plain, and stripping ANSI codes from a colored rendering yields that same text.
"""
from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass, field

from . import __version__
from .codes import RULES, classify


@dataclass
class Note:
    """Secondary location. Prefer `Label` for anything a machine should read."""
    line: int
    col: int
    length: int
    text: str


@dataclass
class Label:
    role: str  # cause | context | definition | expected
    message: str
    line: int
    col: int
    length: int = 1
    filename: str | None = None


@dataclass
class Edit:
    """Replacement of [start, end) in the original file. end column is exclusive."""
    start_line: int
    start_col: int
    end_line: int
    end_col: int
    replacement: str
    filename: str | None = None


@dataclass
class Fix:
    description: str
    applicability: str  # safe | likely | manual
    edits: list[Edit] = field(default_factory=list)
    verified: bool = False
    # One of several guesses for the same diagnostic. When exactly one of them verifies, it becomes `safe`.
    alternative: bool = False


@dataclass
class Diagnostic:
    message: str
    line: int
    col: int
    length: int = 1
    hint: str | None = None
    notes: list[Note] = field(default_factory=list)
    filename: str | None = None
    code: str = ""
    rule: str = ""
    severity: str = "error"
    category: str = "other"
    explanation: str = ""
    labels: list[Label] = field(default_factory=list)
    details: dict = field(default_factory=dict)
    fixes: list[Fix] = field(default_factory=list)
    cause: "Diagnostic | None" = None
    hidden: bool = False
    cascade: bool = False
    id: str = ""


class CompileError(Exception):
    """Compilation failed. `diagnostics` holds every recorded diagnostic, including hidden cascades."""

    def __init__(self, diagnostics: list[Diagnostic]) -> None:
        super().__init__("; ".join(d.message for d in diagnostics))
        self.diagnostics = diagnostics


class DiagnosticBag:
    def __init__(self) -> None:
        self.items: list[Diagnostic] = []

    def error(self, message: str, line: int, col: int, length: int = 1,
              hint: str | None = None, notes: list[Note] | None = None,
              filename: str | None = None, *,
              rule: str | None = None, labels: list[Label] | None = None,
              details: dict | None = None, fixes: list[Fix] | None = None) -> Diagnostic:
        if rule is not None:
            info = RULES[rule]
            det = dict(details or {})
        else:
            info, det = classify(message)
            if details:
                det.update(details)
        diag = Diagnostic(
            message=message, line=line, col=col, length=max(length, 1), hint=hint,
            notes=list(notes or []), filename=filename,
            code=info.code, rule=info.slug, severity="error", category=info.category,
            explanation=info.explanation, labels=list(labels or []), details=det,
            fixes=list(fixes or []),
        )
        self.items.append(diag)
        return diag

    def has_errors(self) -> bool:
        return any(not d.hidden and d.severity == "error" for d in self.items) or any(
            d.severity == "error" for d in self.items)


def prepare(items: list[Diagnostic]) -> list[Diagnostic]:
    """Hide cascade diagnostics and assign ids to the ones that remain.

    Idempotent. Hidden items stay in `items` so `summary.suppressed` can count them.
    """
    if items and getattr(items[0], "_prepared", False):
        return [d for d in items if not d.hidden]
    _suppress(items)
    visible = [d for d in items if not d.hidden]
    visible.sort(key=lambda d: (d.filename or "", d.line, d.col, d.code))
    for i, d in enumerate(visible, 1):
        d.id = f"d{i}"
        for j, fix in enumerate(d.fixes, 1):
            fix.id = f"f{j}"  # type: ignore[attr-defined]
    for d in items:
        d._prepared = True  # type: ignore[attr-defined]
    return visible


def _suppress(items: list[Diagnostic]) -> None:
    """Mark follow-on diagnostics hidden and point them at the root that caused them."""
    seen_syntax: dict[tuple, Diagnostic] = {}
    for d in items:
        # `&&`, `;`, `!` ... are independent and each has its own fix; show every one of them.
        if d.category != "syntax" or d.rule == "foreign-syntax":
            continue
        key = (d.filename, d.line)
        root = seen_syntax.get(key)
        if root is None:
            seen_syntax[key] = d
        else:
            d.hidden = True
            d.cascade = True
            d.cause = root
    syntax_roots = [d for d in items if d.category == "syntax" and not d.hidden]
    for d in items:
        if d.hidden or d.rule != "unexpected-indent":
            continue
        for root in syntax_roots:
            if root.filename == d.filename and root.line == d.line - 1 and root is not d:
                d.hidden = True
                d.cascade = True
                d.cause = root
                break
    seen_name: dict[tuple, Diagnostic] = {}
    for d in items:
        if d.hidden or d.rule not in ("unknown-type", "undefined-name"):
            continue
        name = (d.details or {}).get("name")
        if not name:
            continue
        key = (d.filename, d.rule, name)
        root = seen_name.get(key)
        if root is None:
            seen_name[key] = d
        else:
            d.hidden = True
            d.cascade = True
            d.cause = root
    for d in items:
        if not d.hidden:
            continue
        root = d.cause
        seen: set[int] = set()
        while root is not None and root.hidden and id(root) not in seen:
            seen.add(id(root))
            root = root.cause
        if root is None or root.hidden or root is d:
            d.hidden = False
            d.cascade = False
            d.cause = None


class Style:
    """ANSI wrappers. With `enabled` false, every method returns its text unchanged."""

    def __init__(self, enabled: bool) -> None:
        self.on = enabled

    def _paint(self, text: str, code: str) -> str:
        if not self.on or text == "":
            return text
        return f"\033[{code}m{text}\033[0m"

    def bold_red(self, text: str) -> str:
        return self._paint(text, "1;31")

    def bold_green(self, text: str) -> str:
        return self._paint(text, "1;32")

    def bold_yellow(self, text: str) -> str:
        return self._paint(text, "1;33")

    def blue(self, text: str) -> str:
        return self._paint(text, "34")

    def bold_blue(self, text: str) -> str:
        return self._paint(text, "1;34")

    def bold_cyan(self, text: str) -> str:
        return self._paint(text, "1;36")

    def dim(self, text: str) -> str:
        return self._paint(text, "2")


def use_color(mode: str = "auto", stream=None) -> bool:
    """Whether human diagnostics should include ANSI colors.

    `always` and `never` follow the flag. `auto` colors a terminal, and stays
    plain when `NO_COLOR` is set or `TERM` is `dumb`.
    """
    mode = (mode or "auto").lower()
    stream = sys.stderr if stream is None else stream
    if mode == "never":
        return False
    if mode == "always":
        _enable_vt(stream)
        return True
    if mode != "auto":
        return False
    if os.environ.get("NO_COLOR") is not None:
        return False
    if os.environ.get("TERM", "") == "dumb":
        return False
    isatty = getattr(stream, "isatty", None)
    if not callable(isatty) or not isatty():
        return False
    _enable_vt(stream)
    return True


def _enable_vt(stream) -> None:
    """Turn on ANSI processing for the Windows console. Other platforms already have it."""
    if os.name != "nt" or stream not in (sys.stderr, sys.stdout):
        return
    isatty = getattr(stream, "isatty", None)
    if not callable(isatty) or not isatty():
        return
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        handle_id = -12 if stream is sys.stderr else -11
        handle = kernel32.GetStdHandle(handle_id)
        mode = ctypes.c_uint()
        if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            return
        kernel32.SetConsoleMode(handle, mode.value | 0x0004)
    except (AttributeError, OSError):
        return


def _gutter(width: int, style: Style, line: int | None = None) -> str:
    number = " " * width if line is None else f"{line:>{width}}"
    return f"{style.blue(number)} {style.blue('|')}"


def _mark_span(text: str, col: int, span: int, style: Style) -> str:
    if not style.on:
        return text
    start = max(0, col - 1)
    if start >= len(text):
        return text
    end = min(len(text), start + span)
    return text[:start] + style.bold_red(text[start:end]) + text[end:]


def _snippet(lines: list[str], line: int, col: int, length: int, width: int, label: str = "",
             style: Style | None = None) -> list[str]:
    style = style or Style(False)
    text = lines[line - 1] if 1 <= line <= len(lines) else ""
    if text.endswith("\r"):
        text = text[:-1]
    span = max(1, min(length, max(1, len(text) - col + 1)))
    marker = " " * (col - 1) + style.bold_red("^" * span)
    if label:
        marker += " " + style.bold_cyan(label)
    return [
        _gutter(width, style),
        f"{_gutter(width, style, line)} {_mark_span(text, col, span, style)}",
        f"{_gutter(width, style)} {marker}",
    ]


def _source_for(filename: str | None, primary: str, primary_source: str, sources: dict[str, str] | None) -> str:
    if sources:
        if filename and filename in sources:
            return sources[filename]
        if filename:  # `sub/a.gg` and `sub\a.gg` name the same file
            want = _norm_path(filename)
            for key, text in sources.items():
                if _norm_path(key) == want:
                    return text
        if primary in sources:
            return sources[primary]
    return primary_source


def _norm_path(name: str) -> str:
    import os
    return os.path.normcase(os.path.abspath(name))


def render(diag: Diagnostic, source: str, filename: str, sources: dict[str, str] | None = None,
           *, color: bool = False) -> str:
    """Human rendering of one diagnostic. Every line comes from the diagnostic's fields."""
    style = Style(color)
    target = diag.filename or filename
    src = _source_for(target, filename, source, sources)
    lines = src.splitlines()
    extra = [lb.line for lb in diag.labels] + [n.line for n in diag.notes]
    width = len(str(max([diag.line, *extra]) or 1))
    kind = "Warning" if diag.severity == "warning" else "Error"
    kind_paint = style.bold_yellow if diag.severity == "warning" else style.bold_red
    out = [f"{kind_paint(kind + ':')} {diag.message}",
           f"{' ' * width}{style.bold_blue('-->')} {target}:{diag.line}:{diag.col}  "
           f"{style.bold_red(diag.code)} {style.dim(diag.rule)}"]
    out += _snippet(lines, diag.line, diag.col, diag.length, width, style=style)
    shown: set[tuple] = {(target, diag.line, diag.col)}
    for label in diag.labels:
        lab_file = label.filename or target
        lab_src = _source_for(lab_file, filename, source, sources).splitlines()
        key = (lab_file, label.line, label.col)
        if key in shown:
            continue
        shown.add(key)
        out.append(_gutter(width, style))
        if lab_file != target:
            out.append(f"{' ' * width}{style.bold_blue('-->')} {lab_file}:{label.line}:{label.col}")
        out += _snippet(lab_src, label.line, label.col, label.length, width, label.message, style)[1:]
    for note in diag.notes:
        key = (target, note.line, note.col)
        if key in shown:
            continue
        shown.add(key)
        out.append(_gutter(width, style))
        out += _snippet(lines, note.line, note.col, note.length, width, note.text, style)[1:]
    if diag.hint:
        out.append(f"{' ' * width} {style.bold_cyan('=')} {style.bold_cyan('help:')} {diag.hint}")
    for fix in diag.fixes:
        mark = "verified" if fix.verified else fix.applicability
        out.append(f"{' ' * width} {style.bold_green('=')} {style.bold_green(f'fix ({mark}):')} {fix.description}")
    return "\n".join(out)


def render_all(diags: list[Diagnostic], source: str, filename: str, sources: dict[str, str] | None = None,
               *, color: bool = False) -> str:
    style = Style(color)
    visible = _dedupe(prepare(diags))
    body = "\n\n".join(render(d, source, filename, sources, color=color) for d in visible)
    n = len(visible)
    summary = "1 error found." if n == 1 else f"{n} errors found."
    hidden = sum(1 for d in diags if d.cascade)
    tail = f" {hidden} hidden as cascades." if hidden else ""
    summary = style.bold_red(summary) + (style.dim(tail) if tail else "")
    if not body:
        return summary
    return f"{body}\n\n{summary}"


def _dedupe(items: list[Diagnostic]) -> list[Diagnostic]:
    seen: set[tuple] = set()
    out: list[Diagnostic] = []
    for d in items:
        key = (d.filename, d.line, d.col, d.message)
        if key in seen:
            d.hidden = True
            continue
        seen.add(key)
        out.append(d)
    return out


def position(source: str, line: int, col: int) -> dict:
    """1-based line and Unicode column, 0-based UTF-8 byte offset."""
    parts = source.split("\n")
    if not parts:
        parts = [""]
    line = max(1, min(line, len(parts)))
    raw = parts[line - 1]
    logical = raw[:-1] if raw.endswith("\r") else raw
    column = max(1, min(col, len(logical) + 1))
    pre = "\n".join(parts[:line - 1])
    if line > 1:
        pre += "\n"
    offset = len(pre.encode("utf-8")) + len(logical[:column - 1].encode("utf-8"))
    return {"line": line, "column": column, "offset": offset}


def _span(filename: str, source: str, line: int, col: int, length: int) -> dict:
    start = position(source, line, col)
    end = position(source, line, col + max(length, 1))
    if end["offset"] < start["offset"]:
        end = dict(start)
    return {"file": filename, "start": start, "end": end}


def _file_source(filename: str, primary: str, primary_source: str, sources: dict[str, str]) -> str:
    if filename in sources:
        return sources[filename]
    if primary in sources:
        return sources[primary]
    return primary_source


def export_json(items: list[Diagnostic], sources: dict[str, str], primary: str,
                command: str, primary_source: str = "") -> dict:
    """Machine-readable document. Conforms to docs/gg-diagnostics.schema.json."""
    visible = _dedupe(prepare(items))
    diags = []
    for d in visible:
        filename = d.filename or primary
        source = _file_source(filename, primary, primary_source, sources)
        body: dict = {
            "id": d.id or "d1",
            "code": d.code,
            "rule": d.rule,
            "severity": d.severity,
            "category": d.category,
            "message": d.message,
            "explanation": d.explanation,
            "span": _span(filename, source, d.line, d.col, d.length),
            "caused_by": None,
            "doc": f"gg explain {d.code}",
        }
        if d.labels:
            body["labels"] = []
            for label in d.labels:
                lab_file = label.filename or filename
                lab_src = _file_source(lab_file, primary, primary_source, sources)
                body["labels"].append({
                    "role": label.role,
                    "message": label.message,
                    "span": _span(lab_file, lab_src, label.line, label.col, label.length),
                })
        if d.details:
            body["details"] = d.details
        if d.fixes:
            body["fixes"] = []
            for index, fix in enumerate(d.fixes, 1):
                body["fixes"].append({
                    "id": getattr(fix, "id", None) or f"f{index}",
                    "description": fix.description,
                    "applicability": fix.applicability,
                    "verified": bool(fix.verified),
                    "edits": [_edit_json(edit, filename, primary, primary_source, sources) for edit in fix.edits],
                })
        diags.append(body)
    errors = sum(1 for d in visible if d.severity == "error")
    warnings = sum(1 for d in visible if d.severity == "warning")
    notes = sum(1 for d in visible if d.severity == "note")
    return {
        "schema_version": 1,
        "tool": {"name": "gg", "version": __version__},
        "command": command,
        "ok": errors == 0,
        "summary": {
            "errors": errors,
            "warnings": warnings,
            "notes": notes,
            "suppressed": sum(1 for d in items if d.cascade),
        },
        "diagnostics": diags,
    }


def _edit_json(edit: Edit, filename: str, primary: str, primary_source: str, sources: dict[str, str]) -> dict:
    edit_file = edit.filename or filename
    source = _file_source(edit_file, primary, primary_source, sources)
    return {
        "file": edit_file,
        "start": position(source, edit.start_line, edit.start_col),
        "end": position(source, edit.end_line, edit.end_col),
        "replacement": edit.replacement,
    }


def char_offset(source: str, line: int, col: int) -> int:
    """Code-point offset of a 1-based line/column in `source`."""
    parts = source.split("\n")
    line = max(1, min(line, len(parts) or 1))
    pre = "\n".join(parts[:line - 1])
    if line > 1:
        pre += "\n"
    raw = parts[line - 1] if parts else ""
    logical = raw[:-1] if raw.endswith("\r") else raw
    column = max(1, min(col, len(logical) + 1))
    return len(pre) + (column - 1)


def apply_edits(source: str, edits: list[Edit]) -> str:
    """Apply edits to `source`. Edits are in original coordinates and must not overlap."""
    spans = []
    for edit in edits:
        start = char_offset(source, edit.start_line, edit.start_col)
        end = char_offset(source, edit.end_line, edit.end_col)
        if end < start:
            raise ValueError("edit ends before it starts")
        spans.append((start, end, edit.replacement))
    spans.sort()
    for i in range(1, len(spans)):
        if spans[i][0] < spans[i - 1][1]:
            raise ValueError("overlapping edits")
    text = source
    for start, end, replacement in reversed(spans):
        text = text[:start] + replacement + text[end:]
    return text


def reset_prepared(items: list[Diagnostic]) -> None:
    """Allow `prepare` to run again. Used by tests and by fix verification."""
    for d in items:
        if hasattr(d, "_prepared"):
            del d._prepared
