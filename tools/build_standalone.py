"""Builds `dist/gg` (`dist/gg.exe` on Windows): the compiler as one file that needs no Python installed.

    pip install pyinstaller          # or: pip install -e .[standalone]
    pip install ziglang              # optional: then the file also links with no C compiler installed
    python tools/build_standalone.py
    dist/gg run examples/hello.gg

The file holds Python, llvmlite (with LLVM), the compiler, the Core library, the standard library, and the
debugger printers. When the `ziglang` package is installed it is bundled too, and `gg build` links with
its `zig cc` where no gcc or clang is found, so the file alone builds programs for every target.
"""
from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    if importlib.util.find_spec("PyInstaller") is None:
        print("PyInstaller is not installed: pip install pyinstaller", file=sys.stderr)
        return 1
    build = ROOT / "build" / "standalone"
    build.mkdir(parents=True, exist_ok=True)
    entry = build / "gg_main.py"
    entry.write_text("import sys\nfrom greengold.cli import main\n\nsys.exit(main())\n", encoding="utf-8")
    sep = os.pathsep
    data = [f"{ROOT / 'greengold' / sub}{sep}greengold/{sub}" for sub in ("core", "std", "debug")]
    cmd = [sys.executable, "-m", "PyInstaller", "--onefile", "--noconfirm", "--clean", "--name", "gg",
           "--distpath", str(ROOT / "dist"), "--workpath", str(build / "work"), "--specpath", str(build),
           "--paths", str(ROOT), "--collect-all", "llvmlite", "--collect-submodules", "greengold"]
    for d in data:
        cmd += ["--add-data", d]
    if importlib.util.find_spec("ziglang") is not None:
        cmd += ["--collect-all", "ziglang"]
        print("bundling zig from the ziglang package")
    else:
        print("ziglang is not installed: the file will link with the gcc or clang it finds")
    cmd.append(str(entry))
    res = subprocess.run(cmd, cwd=ROOT)
    if res.returncode != 0:
        return res.returncode
    exe = ROOT / "dist" / ("gg.exe" if sys.platform == "win32" else "gg")
    print(f"built {exe} ({exe.stat().st_size / 1e6:.1f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
