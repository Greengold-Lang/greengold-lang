"""Runs saved findings again with the current compiler: which ones are still accepted and still unsafe?"""
import sys
import tempfile
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))


def one(path):
    import safety_min as M
    work = Path(tempfile.mkdtemp(prefix="ggre_"))
    src = Path(path).read_text(encoding="utf-8")
    return path, M.verdict_kind(src, work)


if __name__ == "__main__":
    files = []
    for a in sys.argv[1:]:
        p = Path(a)
        files += sorted(p.glob("*.gg")) if p.is_dir() else [p]
    with ProcessPoolExecutor(8) as ex:
        for path, kind in ex.map(one, [str(f) for f in files]):
            print(f"{kind:14} {Path(path).name}")
