"""`gg doctor`: check this machine and the current package, and say how to fix each problem."""
from __future__ import annotations

import shutil
import sys
from pathlib import Path


def _line(ok: bool | None, what: str, detail: str = "", fix: str = "") -> bool:
    mark = {True: "ok  ", False: "FAIL", None: "note"}[ok]
    print(f"[{mark}] {what}" + (f": {detail}" if detail else ""))
    if fix and ok is not True:
        print(f"       -> {fix}")
    return ok is not False


def run() -> int:
    from . import __version__
    from .codegen_llvm import init_llvm, native_triple
    from .llvm_driver import PREFERRED_LLVM, backend, find_linker, has_llvmlite, llvmlite_major
    good = True
    print(f"gg {__version__} on {sys.platform}\n")

    good &= _line(sys.version_info >= (3, 10) or getattr(sys, "frozen", False), "Python",
                  sys.version.split()[0], "Python 3.10 or newer is needed (or use the single-file `gg` install).")

    if backend() == "llvmlite":
        ok = has_llvmlite()
        good &= _line(ok, "llvmlite", "installed" if ok else "missing", 'pip install -U "llvmlite>=0.50"')
        if ok:
            init_llvm()
            major = llvmlite_major()
            _line(major >= PREFERRED_LLVM or None, "LLVM", f"{major} (newest supported: {PREFERRED_LLVM})",
                  'pip install -U "llvmlite>=0.50" for faster code')
    else:
        _line(True, "backend", backend())

    triple = native_triple(None) if has_llvmlite() or backend() != "llvmlite" else ""
    linker = find_linker(triple) if triple else None
    good &= _line(linker is not None, "linker", " ".join(linker) if linker else "none found",
                  "install gcc or clang, or run `pip install ziglang` (zig links with nothing else installed)")

    exe = shutil.which("gg")
    _line(exe is not None or None, "gg on PATH", exe or "not found",
          "open a new terminal after installing, or add the install folder to PATH (Windows: %LOCALAPPDATA%\\Greengold; "
          "Linux/macOS: ~/.greengold/bin)")

    cache = Path(".gg-cache")
    _line(None, "build cache", str(cache) + (" (exists)" if cache.exists() else " (created on first build)"))

    from . import tools
    mp = tools.find_manifest()
    if mp is None:
        _line(None, "package", "no gg.toml found here", "create one with `gg new <name>`")
    else:
        try:
            m = tools.load_manifest(mp)
        except Exception as err:  # a broken manifest is exactly what doctor should report
            good &= _line(False, "package", f"{mp}: {err}", "fix gg.toml")
        else:
            main_ok = Path(m.main).is_file()
            good &= _line(main_ok, "package", f"{mp} (main = {m.main})",
                          f"the main file `{m.main}` does not exist; fix `main` in gg.toml")
            if main_ok:
                from .cli import cmd_check
                print("       checking the package...")
                code = cmd_check([str(m.main)], False)
                good &= _line(code == 0, "type-check", "clean" if code == 0 else "errors above",
                              "`gg fix .` applies the verified fixes; `gg explain GGxxxx` explains a code")

    print("\nEverything needed is in place." if good else "\nSome checks failed; fix the FAIL lines above.")
    return 0 if good else 1
