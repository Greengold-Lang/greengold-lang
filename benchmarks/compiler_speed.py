"""Compiler speed: generates a large program (N structs, methods, generics, loops) and times the compiler.

    python benchmarks/compiler_speed.py 300            # ~11k lines: prints check and build times
    python benchmarks/compiler_speed.py 1000 big.gg    # only write the program
"""
import subprocess
import sys
import tempfile
import time
from pathlib import Path

n = int(sys.argv[1]) if len(sys.argv) > 1 else 300
out = []
out.append("struct Pair[A, B]:\n    first: A\n    second: B\n")
out.append("fn biggest[T: Ord](a: T, b: T) -> T:\n    if a > b:\n        return a\n    return b\n")
for i in range(n):
    out.append(f"""struct S{i}:
    id: i64
    name: string
    tags: List[i32]

impl S{i}:
    fn score(self) -> i64:
        t: i64 = self.id
        for x in self.tags:
            t += i64(x)
        return t

    fn rename(self: lend Self, s: str):
        self.name = s.to_string()

fn make{i}(k: i64) -> S{i}:
    tags = List[i32]()
    for j in 0..10:
        tags.push(j * {i % 7 + 1})
    return S{i}{{ id: k, name: f"s{{k}}", tags: tags }}

fn work{i}(n: i64) -> i64:
    s = make{i}(n)
    s.rename("x")
    p = Pair{{ first: s.score(), second: biggest(n, {i}) }}
    total: i64 = 0
    while total < 100:
        total += p.first + p.second
        if total % 3 == 0:
            break
    match Valid(total):
        Valid(v):
            return v
        None:
            return 0
""")
out.append("fn main():\n    t: i64 = 0\n" + "".join(f"    t += work{i}({i})\n" for i in range(n)) + "    print(t)\n")
text = "\n".join(out)
if len(sys.argv) > 2:
    Path(sys.argv[2]).write_text(text, encoding="utf-8")
else:
    with tempfile.TemporaryDirectory() as d:
        src = Path(d) / "big.gg"
        src.write_text(text, encoding="utf-8")
        print(f"{text.count(chr(10)) + 1} lines")
        for cmd in (["check", str(src)], ["build", str(src), "-o", str(Path(d) / "big.exe")]):
            t0 = time.perf_counter()
            subprocess.run([sys.executable, "-m", "greengold", *cmd], check=True, capture_output=True, cwd=d)
            print(f"gg {cmd[0]}: {time.perf_counter() - t0:.2f}s")
