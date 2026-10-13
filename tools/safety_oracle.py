"""A run-time oracle for memory safety, built on the language's own `allocator` hook.

Every program is built once with an allocator that never gives memory back. The binary is then run twice:

  * mode LEAK  : `free` does nothing to the bytes, so a read through a dangling pointer still sees the old
                 data. This is the "ideal" meaning of the program.
  * mode POISON: `free` (and the old block of a `resize`) is filled with 0xDD. At exit every freed block is
                 checked to still be all 0xDD, so a WRITE through a dangling pointer shows up too.

In both modes a block has a guard word and a tail canary: a bad or double `free` stops the program with exit code
99, a write past the end of a block with 97, and a write into freed memory with 98. At exit the program prints
`GG_ORACLE_LIVE <n>`, the number of heap blocks still allocated (a leak when it is not 0).

If the two runs differ in exit code or output, the program read memory that had been freed. A program that
the compiler accepted must never do that (outside `unsafe:`, `extern`, and `--unchecked`).

    from safety_oracle import check_program
    verdict = check_program(source_text, workdir)
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

PRELUDE = r'''extern "stdlib.h" fn malloc(gg_n: usize) -> *mut u8
extern "stdlib.h" fn _exit(gg_code: i32)
extern "stdlib.h" fn atexit(gg_f: fn()) -> i32
extern "stdlib.h" fn getenv(gg_name: str) -> *u8
extern "stdio.h" fn puts(gg_s: str) -> i32
extern "stdio.h" fn printf(gg_f: str, ...) -> i32 as gg_printf
extern "string.h" fn memset(gg_p: *mut u8, gg_c: i32, gg_n: usize) -> *mut u8
extern "string.h" fn memcpy(gg_d: *mut u8, gg_s: *u8, gg_n: usize) -> *mut u8

static GG_MODE: i64 = -1
static GG_BLOCKS: i64 = 0
static GG_FREED: u64 = 0
static GG_LOCK: i64 = 0

fn gg_oracle_exit():
    unsafe:
        if GG_MODE == 1:
            gg_cur = GG_FREED
            while gg_cur != 0:
                gg_raw = int_to_ptr[*mut u8](usize(gg_cur))
                gg_h = ptr_cast[*mut u64](gg_raw)
                gg_n = usize(gg_h[0])
                gg_user = ptr_offset(gg_raw, 32)
                for gg_i in 0..gg_n:
                    if gg_user[gg_i] != 0xDD:
                        puts("ORACLE: write after free")
                        _exit(98)
                gg_cur = gg_h[2]
        gg_printf("GG_ORACLE_LIVE %d\n", i32(GG_BLOCKS))

fn gg_oracle_init():
    unsafe:
        if GG_MODE < 0:
            gg_e = getenv("GG_ORACLE")
            if gg_e == null:
                GG_MODE = 0
            else:
                GG_MODE = 1
            atexit(gg_oracle_exit)

fn gg_oracle_alloc(gg_n: usize) -> *mut u8:
    unsafe:
        gg_oracle_init()
        gg_raw = malloc(gg_n + 40)
        if gg_raw == null:
            return null
        gg_h = ptr_cast[*mut u64](gg_raw)
        gg_h[0] = u64(gg_n)
        gg_h[1] = 0xA11CE
        gg_h[2] = 0
        gg_h[3] = 0
        gg_user = ptr_offset(gg_raw, 32)
        memset(ptr_offset(gg_user, isize(gg_n)), 0xFC, 8)
        atomic_add[i64](addr_mut(GG_BLOCKS), 1, "seq_cst")
        return gg_user

fn gg_oracle_free(gg_p: *mut u8):
    unsafe:
        if gg_p == null:
            return
        gg_raw = ptr_offset(gg_p, -32)
        gg_h = ptr_cast[*mut u64](gg_raw)
        if gg_h[1] != 0xA11CE:
            puts("ORACLE: bad or double free")
            _exit(99)
        gg_n = usize(gg_h[0])
        gg_t = ptr_offset(gg_p, isize(gg_n))
        for gg_i in 0..8:
            if gg_t[gg_i] != 0xFC:
                puts("ORACLE: heap overflow")
                _exit(97)
        gg_h[1] = 0xDEAD
        atomic_sub[i64](addr_mut(GG_BLOCKS), 1, "seq_cst")
        if GG_MODE == 1:
            memset(gg_p, 0xDD, gg_n)
            while atomic_cas[i64](addr_mut(GG_LOCK), 0, 1, "seq_cst") != 0:
                pass
            gg_h[2] = GG_FREED
            GG_FREED = u64(ptr_to_int(gg_raw))
            atomic_store[i64](addr_mut(GG_LOCK), 0, "seq_cst")

fn gg_oracle_resize(gg_p: *mut u8, gg_n: usize) -> *mut u8:
    unsafe:
        gg_new = gg_oracle_alloc(gg_n)
        if gg_p == null:
            return gg_new
        if gg_new == null:
            return null
        gg_raw = ptr_offset(gg_p, -32)
        gg_h = ptr_cast[*mut u64](gg_raw)
        gg_len = usize(gg_h[0])
        if gg_n < gg_len:
            gg_len = gg_n
        memcpy(gg_new, gg_p, gg_len)
        gg_oracle_free(gg_p)
        return gg_new

allocator gg_oracle_alloc, gg_oracle_resize, gg_oracle_free

'''

# Programs that opt out of the guarantee, or that cannot be compared run for run.
UNSAFE_WORDS = re.compile(r"\b(unsafe|extern|asm|allocator|volatile_read|volatile_write)\b|--unchecked")
NONDET_WORDS = re.compile(r"\b(thread|tasks?|spawn|input|time|clock|random|rand|env|process|net|fs|file|socket)\b")

BUILD_TIMEOUT = 120
RUN_TIMEOUT = 5
STACK_OVERFLOW = 3221225725  # 0xC00000FD: endless recursion is a crash, not a memory-safety hole


@dataclass
class Verdict:
    kind: str  # rejected | skipped | ok | mismatch | double_free | crash | nondeterministic | timeout | build_error
    detail: str = ""
    stdout_leak: bytes = b""
    stdout_poison: bytes = b""
    errors: str = ""
    live: int = 0  # heap blocks still allocated when the program ended


def with_prelude(src: str) -> str:
    """Puts the oracle allocator after the leading imports and comments (imports come first)."""
    lines = src.splitlines(keepends=True)
    i = 0
    while i < len(lines) and (not lines[i].strip() or lines[i].lstrip().startswith(("import ", "#"))):
        i += 1
    return "".join(lines[:i]) + PRELUDE + "".join(lines[i:])


LIVE_LINE = re.compile(rb"GG_ORACLE_LIVE (-?\d+)\r?\n?")


def is_crash(code) -> bool:
    """A fault of the process (access violation, abort, signal), not an exit code the program chose."""
    if not isinstance(code, int) or code == STACK_OVERFLOW:
        return False
    return code < 0 or code >= 0x80000000 or code in (134, 136, 138, 139)


def split_live(out: bytes) -> tuple[bytes, int | None]:
    """Takes the `GG_ORACLE_LIVE n` line the oracle prints at exit out of the program's output."""
    m = None
    for m in LIVE_LINE.finditer(out):
        pass
    if m is None:
        return out, None
    return out[:m.start()] + out[m.end():], int(m.group(1))


def _run(cmd, env=None, timeout=RUN_TIMEOUT):
    try:
        p = subprocess.run(cmd, stdin=subprocess.DEVNULL, capture_output=True, timeout=timeout, env=env)
        return p.returncode, p.stdout, p.stderr
    except subprocess.TimeoutExpired:
        return "timeout", b"", b""


def accepted(src: str) -> tuple[bool, str]:
    """Does the compiler accept the program (`gg check`, imports included)? Returns (ok, error text)."""
    from greengold.cli import analyze

    _program, _sources, diags, _checker = analyze([], initial_source=src, initial_filename="<fuzz>.gg")
    errs = [d for d in diags.items if getattr(d, "severity", "error") == "error"]
    return (not errs), "; ".join(f"{getattr(d, 'code', '?')}: {d.message}" for d in errs[:3])


def check_program(src: str, workdir: Path, name: str | None = None, release: bool = False) -> Verdict:
    """Builds `src` with the oracle allocator, runs it in both modes, and compares."""
    workdir.mkdir(parents=True, exist_ok=True)
    name = name or uuid.uuid4().hex[:10]
    path = workdir / f"{name}.gg"
    exe = workdir / (f"{name}.exe" if os.name == "nt" else name)
    path.write_text(with_prelude(src), encoding="utf-8")
    cmd = [sys.executable, "-m", "greengold", "build", str(path), "-o", str(exe)]
    if release:
        cmd.append("--release")
    try:
        code, out, err = _run(cmd, timeout=BUILD_TIMEOUT)
        if code != 0 or not exe.exists():
            return Verdict("build_error", errors=(err or out).decode("utf-8", "replace")[-400:])
        base = dict(os.environ)
        base.pop("GG_ORACLE", None)
        poisoned = dict(base, GG_ORACLE="1")
        a = _run([str(exe)], base)
        if a[0] == "timeout":
            return Verdict("timeout", detail="leak mode")
        a2 = _run([str(exe)], base)
        b = _run([str(exe)], poisoned)
        if a[0] == "timeout" or b[0] == "timeout":
            return Verdict("timeout", detail=f"leak={a[0]} poison={b[0]}")
        if a[:2] != a2[:2]:
            if src.count(".spawn(") > src.count(".join()"):
                return Verdict("skipped", detail="unjoined threads")
            return Verdict("nondeterministic")
        codes = {"double_free": 99, "heap_overflow": 97, "write_after_free": 98}
        for kind, code in codes.items():
            if a[0] == code or b[0] == code:
                return Verdict(kind, detail=(b[1] if b[0] == code else a[1]).decode("utf-8", "replace")[-100:],
                               stdout_leak=a[1], stdout_poison=b[1])
        for label, r in (("leak", a), ("poison", b)):
            if is_crash(r[0]):
                return Verdict("crash", detail=f"{label} mode exit {r[0]}", stdout_leak=a[1], stdout_poison=b[1],
                               errors=r[2].decode("utf-8", "replace")[-300:])
        out_a, live_a = split_live(a[1])
        out_b, live_b = split_live(b[1])
        if (a[0], out_a) != (b[0], out_b):
            return Verdict("mismatch", detail=f"exit {a[0]} vs {b[0]}", stdout_leak=out_a, stdout_poison=out_b)
        # a thread that is still closing down can make the two counts differ: only a count both runs agree on is a leak
        # a panic ends the process without running drops, so only a clean exit can leak
        clean = a[0] == 0 and b[0] == 0
        # a thread that is never joined may still be running when `main` returns: its captures are not a leak
        if src.count(".spawn(") > src.count(".join()"):
            clean = False
        return Verdict("ok", stdout_leak=out_a, live=min(live_a or 0, live_b or 0) if clean else 0)
    finally:
        for p in (path, exe, exe.with_suffix(".o")):
            try:
                p.unlink()
            except OSError:
                pass
