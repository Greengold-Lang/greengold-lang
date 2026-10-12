"""Build the browser playground bundle: ``website/playground/gg-bundle.zip``.

The zip holds the compiler front end (``greengold/``) and the pure-Python half of ``llvmlite`` (``llvmlite.ir``);
Pyodide unpacks it and ``greengold.web`` answers check, fix, format, and explain. Run from anywhere:

    python tools/build_playground.py
"""
from __future__ import annotations

import json
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "website" / "playground"
EXAMPLES = ["hello", "fibonacci", "modes", "generics", "heap_list", "list_ops", "match_guards", "iterator"]


def add_tree(z: zipfile.ZipFile, base: Path, rel: Path, keep) -> None:
    for p in sorted((base / rel).rglob("*")):
        if p.is_file() and "__pycache__" not in p.parts and keep(p):
            z.write(p, p.relative_to(base).as_posix())


def main() -> None:
    import llvmlite
    ll = Path(llvmlite.__file__).parent
    OUT.mkdir(exist_ok=True)
    with zipfile.ZipFile(OUT / "gg-bundle.zip", "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        add_tree(z, ROOT, Path("greengold"), lambda p: p.suffix in (".py", ".gg") and "debug" not in p.parts)
        for name in ("__init__.py", "_version.py"):
            z.write(ll / name, f"llvmlite/{name}")
        add_tree(z, ll.parent, Path("llvmlite") / "ir", lambda p: p.suffix == ".py")
    examples = {n: (ROOT / "examples" / f"{n}.gg").read_text(encoding="utf-8") for n in EXAMPLES}
    (OUT / "examples.json").write_text(json.dumps(examples, indent=1), encoding="utf-8")
    print("wrote", (OUT / "gg-bundle.zip").stat().st_size // 1024, "KiB bundle and", len(examples), "examples")


if __name__ == "__main__":
    main()
