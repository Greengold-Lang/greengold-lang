"""Rendered diagnostics, compared with `tests/snapshots/*.txt`.

Each case is a small program with one mistake. The whole rendered text (message, location, labels, notes,
help, fixes) must match the snapshot. After an intended wording change, regenerate with:

    GG_UPDATE_SNAPSHOTS=1 python -m pytest tests/test_diagnostic_snapshots.py
"""
from __future__ import annotations

import io
import os
import re
from pathlib import Path

import pytest

from greengold.diagnostics import render_all, reset_prepared
from tests.helpers import front_end

SNAPSHOTS = Path(__file__).parent / "snapshots"

CASES = {
    "use_after_move": """\
fn main():
    v = List[i32]()
    w = v
    print(v.len, w.len)
""",
    "inferred_lend_needs_var": """\
fn add(xs: List[i32]):
    xs.push(1)

fn main():
    fixed v = List[i32]()
    add(v)
""",
    "closure_lend_capture_in_use": """\
fn main():
    out = List[i32]()
    collect = fn(x: i32) => out.push(x)
    print(out.len)
    collect(1)
""",
    "closure_capture_borrowed": """\
fn main():
    v = List[i32]()
    f = fn(i: i32) -> usize => v.len
    v.push(1)
    print(f(0))
""",
    "shared_is_read_only": """\
fn main():
    s = Shared[List[i32]](List[i32]())
    s.value.push(1)
""",
    "list_element_move_out": """\
fn main():
    names = List[string]()
    names.push(string.from("a"))
    first = names[0]
""",
    "unhashable_key": """\
struct Q:
    a: f64

fn main():
    print(hash(Q{ a: 1.0 }))
""",
}


@pytest.mark.parametrize("name", sorted(CASES))
def test_diagnostic_snapshot(name: str):
    src = CASES[name]
    diags = front_end(src)[1]
    assert diags, f"{name}: expected a diagnostic"
    text = render_all(diags, src, "example.gg").replace("\r\n", "\n").rstrip() + "\n"
    path = SNAPSHOTS / f"{name}.txt"
    if os.environ.get("GG_UPDATE_SNAPSHOTS") or not path.exists():
        SNAPSHOTS.mkdir(exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
    assert text == path.read_text(encoding="utf-8")


_ANSI = re.compile(r"\033\[[0-9;]*m")


def _strip_ansi(text: str) -> str:
    return _ANSI.sub("", text)


@pytest.mark.parametrize("name", sorted(CASES))
def test_color_adds_ansi_without_changing_text(name: str):
    src = CASES[name]
    diags = front_end(src)[1]
    plain = render_all(diags, src, "example.gg")
    reset_prepared(diags)
    painted = render_all(diags, src, "example.gg", color=True)
    assert "\033[" not in plain
    assert "\033[1;31mError:" in painted
    assert "\033[1;31m^" in painted
    assert _strip_ansi(painted) == plain


def test_use_color_follows_terminal_and_no_color(monkeypatch):
    from greengold.diagnostics import use_color

    class _TTY:
        def isatty(self) -> bool:
            return True

    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setenv("TERM", "xterm-256color")
    assert use_color("auto", _TTY()) is True
    assert use_color("never", _TTY()) is False
    assert use_color("auto", io.StringIO()) is False
    monkeypatch.setenv("NO_COLOR", "")
    assert use_color("auto", _TTY()) is False
    assert use_color("always", _TTY()) is True
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setenv("TERM", "dumb")
    assert use_color("auto", _TTY()) is False


def test_cli_color_flag(tmp_path, capsys):
    from greengold import cli

    path = tmp_path / "t.gg"
    path.write_text("fn main():\n    print(y)\n", encoding="utf-8")
    try:
        assert cli.main(["--color", "always", "check", str(path)]) == 1
        assert "\033[1;31mError:" in capsys.readouterr().err
        assert cli.main(["check", "--color", "never", str(path)]) == 1
        assert "\033[" not in capsys.readouterr().err
        args = cli.build_arg_parser().parse_args(["check", "a.gg"])
        assert args.color == "auto"
    finally:
        cli._COLOR = False
