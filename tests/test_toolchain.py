"""Linking without a system C compiler: `zig cc` (ziglang / $GG_ZIG / PATH), and `gg toolchain`."""
import json
import shutil
import sys

import pytest

from greengold import targets
from greengold.cli import main


def test_zig_target_names():
    assert targets.zig_target("x86_64-w64-windows-gnu") == "x86_64-windows-gnu"
    assert targets.zig_target("aarch64-unknown-linux-gnu") == "aarch64-linux-gnu"
    assert targets.zig_target("x86_64-unknown-linux-musl") == "x86_64-linux-musl"
    assert targets.zig_target("aarch64-apple-darwin") == "aarch64-macos"
    assert targets.zig_target("thumbv7em-none-eabihf") == "thumb-freestanding-eabihf"


def test_zig_is_the_last_resort_for_another_machine(monkeypatch, tmp_path):
    fake = tmp_path / ("zig.exe" if sys.platform == "win32" else "zig")
    fake.write_text("", encoding="utf-8")
    monkeypatch.setenv("GG_ZIG", str(fake))
    monkeypatch.delenv("GG_LINKER", raising=False)
    monkeypatch.delenv("GG_SYSROOT", raising=False)
    monkeypatch.setattr(targets.shutil, "which", lambda _name: None)
    assert targets.cross_linker("aarch64-unknown-linux-gnu", False) == [str(fake), "cc", "-target", "aarch64-linux-gnu"]
    monkeypatch.delenv("GG_ZIG")
    monkeypatch.setattr(targets.importlib.util, "find_spec", lambda _name: None)
    assert targets.cross_linker("aarch64-unknown-linux-gnu", False) is None


@pytest.mark.skipif(shutil.which("gcc") is None, reason="the stand-in zig hands off to gcc")
def test_build_links_through_zig_cc(monkeypatch, tmp_path):
    log = tmp_path / "zig_args.json"
    shim = tmp_path / "fake_zig.py"
    shim.write_text(
        "import json, subprocess, sys\n"
        f"open({str(log)!r}, 'w').write(json.dumps(sys.argv[1:]))\n"
        "args = sys.argv[1:]\n"
        "assert args[0] == 'cc' and args[1] == '-target'\n"
        "sys.exit(subprocess.run(['gcc'] + args[3:]).returncode)\n", encoding="utf-8")
    if sys.platform == "win32":
        zig = tmp_path / "zig.bat"
        zig.write_text(f'@"{sys.executable}" "{shim}" %*\n', encoding="utf-8")
    else:
        zig = tmp_path / "zig"
        zig.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{shim}" "$@"\n', encoding="utf-8")
        zig.chmod(0o755)
    monkeypatch.setenv("GG_ZIG", str(zig))
    monkeypatch.setenv("GG_LINKER", "zig")
    monkeypatch.chdir(tmp_path)
    src = tmp_path / "hello.gg"
    src.write_text('fn main():\n    print("linked by zig")\n', encoding="utf-8")
    exe = tmp_path / ("hello.exe" if sys.platform == "win32" else "hello")
    assert main(["build", str(src), "-o", str(exe)]) == 0
    args = json.loads(log.read_text(encoding="utf-8"))
    from greengold.codegen_llvm import native_triple
    assert args[:3] == ["cc", "-target", targets.zig_target(native_triple(None))]
    import subprocess
    assert subprocess.run([str(exe)], capture_output=True, text=True).stdout.strip() == "linked by zig"


def test_toolchain_report(capsys):
    code = main(["toolchain"])
    out = capsys.readouterr().out
    assert "llvmlite" in out and "LLVM" in out and "linker" in out and "zig" in out
    assert code in (0, 1)
