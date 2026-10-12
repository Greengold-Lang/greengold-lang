"""Two-level self-inlining before LLVM's own optimizer.

GCC inlines a small directly recursive function into itself a couple of times.
LLVM will not inline a function into itself, so the same recursion stays a
call. Cloning the body twice and marking the clones `alwaysinline` makes
LLVM's inliner do that expansion; the rest of -O3 then cleans it up.
"""
from __future__ import annotations

import re

_MAX_BODY = 8000
_MAX_SELF_CALLS = 3


def _spans(ir: str) -> list[tuple[int, int]]:
    """Byte spans [start, end) of each `define` in `ir`."""
    spans: list[tuple[int, int]] = []
    pos = 0
    while True:
        start = ir.find("\ndefine ", pos)
        if start < 0:
            if pos == 0 and ir.startswith("define "):
                start = 0
            else:
                break
        else:
            start += 1  # keep the 'd' of define; drop the newline
        brace = ir.find("{", start)
        if brace < 0:
            break
        end = ir.find("\n}", brace)
        if end < 0:
            break
        end = end + 2  # include '\n}'
        if end < len(ir) and ir[end] == "\n":
            end += 1
        spans.append((start, end))
        pos = end
    return spans


def _token(header: str) -> str | None:
    match = re.search(r'@("(?:[^"\\]|\\.)+"|[A-Za-z0-9_$.]+)', header)
    if match is None:
        return None
    return match.group(1)


def _at(token: str) -> str:
    return "@" + token


def _with_suffix(token: str, suffix: str) -> str:
    if token.startswith('"'):
        return f'@"{token[1:-1]}{suffix}"'
    return f"@{token}{suffix}"


def _retarget(text: str, token: str, dest: str) -> str:
    return re.sub(re.escape(_at(token)) + r"(?=\s*\()", dest, text)


def _alwaysinline(header: str) -> str:
    if "alwaysinline" in header:
        return header
    brace = header.rfind("{")
    if brace < 0:
        return header + " alwaysinline"
    prefix = header[:brace].rstrip()
    return prefix + " alwaysinline {"


def _clone(header: str, body: str, token: str, suffix: str, call_dest: str) -> str:
    cloned_header = _alwaysinline(_retarget(header, token, _with_suffix(token, suffix)))
    cloned_body = _retarget(body, token, call_dest)
    return cloned_header + cloned_body


def recur_inline(ir: str) -> str:
    """Rewrite `ir`, one recursive function at a time, until none remain eligible."""
    spans = _spans(ir)
    for start, end in spans:
        chunk = ir[start:end]
        brace = chunk.find("{")
        if brace < 0:
            continue
        header, body = chunk[: brace + 1], chunk[brace + 1 :]
        token = _token(header)
        if token is None or any(flag in header for flag in ("noinline", "optnone", "alwaysinline")):
            continue
        calls = len(re.findall(re.escape(_at(token)) + r"\s*\(", body))
        if not (1 <= calls <= _MAX_SELF_CALLS) or len(chunk) > _MAX_BODY:
            continue
        renamed = _retarget(chunk, token, _with_suffix(token, ".ri1"))
        # The define is the first occurrence; calls stay pointed at the clone.
        renamed = renamed.replace(_with_suffix(token, ".ri1"), _at(token), 1)
        ri1 = _clone(header, body, token, ".ri1", _with_suffix(token, ".ri2"))
        ri2 = _clone(header, body, token, ".ri2", _at(token))
        updated = ir[:start] + renamed + "\n" + ri1 + "\n" + ri2 + ir[end:]
        return recur_inline(updated)
    return ir
