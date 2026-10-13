"""Runs every program of the seed corpus under the oracle: a program the compiler accepts must behave the same
with a poisoning allocator as with a leaking one."""
import collections
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import safety_corpus
import safety_oracle as O

work = Path(tempfile.mkdtemp(prefix="ggsafe_"))
corpus = safety_corpus.collect()
rows = []


def one(item):
    name, src = item
    if O.UNSAFE_WORDS.search(src):
        return name, O.Verdict("skipped", "unsafe/extern")
    ok, errs = O.accepted(src)
    if not ok:
        return name, O.Verdict("rejected", errs)
    return name, O.check_program(src, work)


with ThreadPoolExecutor(8) as ex:
    for name, v in ex.map(one, corpus.items()):
        rows.append((name, v))
c = collections.Counter(v.kind for _, v in rows)
print(dict(c))
leaks = [(n, v.live) for n, v in rows if v.kind == "ok" and v.live]
print("programs that end with live heap blocks:", len(leaks), leaks[:12])
for name, v in rows:
    if v.kind in ("mismatch", "double_free", "crash", "build_error", "timeout", "nondeterministic"):
        print(f"{v.kind:15} {name}  {v.detail[:120]}  {v.errors[:200]!r}")
