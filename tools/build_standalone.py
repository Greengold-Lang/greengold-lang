"""Builds `dist/gg/` (`gg.exe` on Windows, `gg` elsewhere, next to an `_internal` folder): the compiler as a
folder that needs no Python installed.

    pip install pyinstaller          # or: pip install -e .[standalone]
    pip install ziglang              # optional: then the folder also links with no C compiler installed
    python tools/build_standalone.py
    dist/gg/gg run examples/hello.gg
    python tools/build_standalone.py --pack out/gg-linux-x64.tar.gz   # the release archive (.zip on Windows)

The folder holds Python, llvmlite (with LLVM), the compiler, the Core library, the standard library, and the
debugger printers. When the `ziglang` package is installed it is bundled too, and `gg build` links with
its `zig cc` where no gcc or clang is found, so the folder alone builds programs for every target.

It is a folder, not one file, on purpose: a PyInstaller one-file build unpacks itself into a temp folder on
every start, which took 10 to 25 seconds on Windows (every extracted file is scanned by the antivirus).
"""
from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main(onefile: bool = False) -> int:
    if importlib.util.find_spec("PyInstaller") is None:
        print("PyInstaller is not installed: pip install pyinstaller", file=sys.stderr)
        return 1
    build = ROOT / "build" / ("onefile" if onefile else "standalone")
    build.mkdir(parents=True, exist_ok=True)
    entry = build / "gg_main.py"
    entry.write_text("import sys\nfrom greengold.cli import main\n\nsys.exit(main())\n", encoding="utf-8")
    sep = os.pathsep
    data = [f"{ROOT / 'greengold' / sub}{sep}greengold/{sub}" for sub in ("core", "std", "debug")]
    cmd = [sys.executable, "-m", "PyInstaller", "--onefile" if onefile else "--onedir", "--noconfirm", "--clean", "--name", "gg",
           "--distpath", str(ROOT / "dist" / ("onefile" if onefile else "")), "--workpath", str(build / "work"), "--specpath", str(build),
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
    name = "gg.exe" if sys.platform == "win32" else "gg"
    exe = ROOT / "dist" / "onefile" / name if onefile else ROOT / "dist" / "gg" / name
    print(f"built {exe}")
    return 0


def pack(archive: Path) -> None:
    """Archive the contents of `dist/gg/` (no wrapping folder): `.zip` on Windows, `.tar.gz` elsewhere."""
    src = ROOT / "dist" / "gg"
    archive.parent.mkdir(parents=True, exist_ok=True)
    if archive.name.endswith(".zip"):
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as z:
            for path in sorted(src.rglob("*")):
                if path.is_file():
                    z.write(path, path.relative_to(src).as_posix())
    else:
        with tarfile.open(archive, "w:gz") as t:
            for path in sorted(src.iterdir()):
                t.add(path, arcname=path.name)
    print(f"packed {archive} ({archive.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--pack":
        pack(Path(sys.argv[2]))
        sys.exit(0)
    sys.exit(main(onefile="--onefile" in sys.argv[1:]))
