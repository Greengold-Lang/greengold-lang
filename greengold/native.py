"""C and C++ sources built with a package (`[native]` in gg.toml).

    [native]
    sources = ["native/shim.cpp", "native/fast.c"]   # compiled and linked into the program
    flags = ["-O2"]                                   # extra compiler flags (optional)
    libs = ["sqlite3"]                                # extra libraries to link (optional)

A `.c` file is compiled with `$CC` (else gcc, clang, cc), a `.cpp`/`.cc`/`.cxx` file with `$CXX` (else
g++, clang++, c++), and a program with C++ in it links the C++ runtime. Objects are cached in
`.gg-cache/native` by the content of the source and the flags. Dependencies' `[native]` sections are
built too, each relative to its own package.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib
from dataclasses import dataclass, field
from pathlib import Path

CXX_EXT = {".cpp", ".cc", ".cxx", ".c++"}


@dataclass
class Native:
    sources: list[tuple[Path, list[str]]] = field(default_factory=list)  # (file, flags)
    libs: list[str] = field(default_factory=list)

    @property
    def has_cxx(self) -> bool:
        return any(p.suffix.lower() in CXX_EXT for p, _ in self.sources)


class NativeError(Exception):
    pass


def read(root: Path, into: Native) -> None:
    """Adds the `[native]` section of the package at `root`, if any."""
    manifest = root / "gg.toml"
    if not manifest.is_file():
        return
    section = tomllib.loads(manifest.read_text(encoding="utf-8")).get("native", {}) or {}
    flags = [str(f) for f in section.get("flags", [])]
    for src in section.get("sources", []):
        path = (root / str(src)).resolve()
        if not path.is_file():
            raise NativeError(f"{manifest}: native source not found: {src}")
        into.sources.append((path, flags))
    into.libs.extend(str(lib) for lib in section.get("libs", []) if str(lib) not in into.libs)


def _compiler(cxx: bool) -> str:
    env = os.environ.get("CXX" if cxx else "CC")
    if env and shutil.which(env):
        return shutil.which(env)  # type: ignore[return-value]
    for name in (("g++", "clang++", "c++") if cxx else ("gcc", "clang", "cc")):
        found = shutil.which(name)
        if found:
            return found
    raise NativeError(f"no {'C++' if cxx else 'C'} compiler found (set {'CXX' if cxx else 'CC'})")


def build(native: Native, cache: Path) -> list[str]:
    """Compiles every source (or takes it from the cache); returns linker inputs."""
    out: list[str] = []
    cache.mkdir(parents=True, exist_ok=True)
    for path, flags in native.sources:
        cxx = path.suffix.lower() in CXX_EXT
        cc = _compiler(cxx)
        key = hashlib.sha256(path.read_bytes() + repr((flags, cc, str(path.parent))).encode()).hexdigest()[:20]
        obj = cache / f"{path.stem}-{key}.o"
        if not obj.is_file():
            cmd = [cc, "-c", str(path), "-o", str(obj), f"-I{path.parent}", *flags]
            res = subprocess.run(cmd, capture_output=True, text=True)
            if res.returncode != 0:
                raise NativeError(f"compiling {path.name} failed:\n{res.stderr or res.stdout}")
        out.append(str(obj))
    if native.has_cxx:
        out.append("-lstdc++")
    out.extend(f"-l{lib}" for lib in native.libs)
    return out
