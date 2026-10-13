"""Shrinks every still-failing finding of a directory in parallel and prints the distinct minimal programs."""
import collections
import re
import sys
import tempfile
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))


def one(path):
    import safety_min as M
    work = Path(tempfile.mkdtemp(prefix="ggma_"))
    src = Path(path).read_text(encoding="utf-8")
    kind = M.verdict_kind(src, work)
    if kind == "rejected":
        return path, kind, ""
    return path, kind, M.minimize(src, kind, work, only_main=False)


if __name__ == "__main__":
    files = []
    for a in sys.argv[1:]:
        p = Path(a)
        files += sorted(p.glob("*.gg")) if p.is_dir() else [p]
    groups = collections.OrderedDict()
    with ProcessPoolExecutor(8) as ex:
        for path, kind, text in ex.map(one, [str(f) for f in files]):
            if kind == "rejected":
                continue
            body = text[text.index("fn main"):] if "fn main" in text else text
            key = re.sub(r"\bv\d+\b", "v", body)
            groups.setdefault((kind, key), []).append(Path(path).name)
            out = Path(path).with_suffix(".min.gg")
            out.write_text(text, encoding="utf-8")
    for (kind, key), names in groups.items():
        print(f"=== {kind} x{len(names)} {names[:3]}")
        print(key)
