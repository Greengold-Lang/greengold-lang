"""`gg fuzz`: feed a function random bytes until something stops the program.

    fn fuzz_target(data: []u8):
        parse_packet(data)            # must never panic, whatever the bytes

    gg fuzz parser.gg --runs 20000 --corpus corpus/

The target is any function `fn fuzz_target(data: []u8)` in the file (the file's own `main` is not used). `gg fuzz` builds the
program once with the coverage probes of `gg coverage`, then runs it again and again on mutated inputs. An input that executes a
statement or branch no earlier input did is kept (and written to `--corpus`), so the search follows the code into new places. A
run that exits abnormally (a panic, a failed bounds or overflow check, a crash, or a timeout) is a finding: the input is
shrunk and saved in `--crashes` (default `fuzz-crashes/`) with a name made from its hash, and the run ends unless
`--keep-going` is given. Replay one with `gg run parser.gg` using the same harness, or `gg fuzz parser.gg --replay FILE`.

It is a small mutation fuzzer (bit flips, byte changes, insertions, deletions, chunk copies, splices between corpus entries,
and interesting integers), not a replacement for AFL or libFuzzer; its job is to make "fuzzed with N million runs, no findings"
a one-line check in a project. The seed makes a run repeatable: `--seed 7` always tries the same inputs in the same order.
"""
from __future__ import annotations

import hashlib
import os
import random
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

INTERESTING = [b"\x00", b"\x01", b"\x7f", b"\x80", b"\xff", b"\x00\x00", b"\xff\xff", b"\x00\x80", b"\xff\x7f",
               b"\x00\x00\x00\x00", b"\xff\xff\xff\xff", b"\x00\x00\x00\x80", b"\xff\xff\xff\x7f"]
_MAIN = re.compile(r"^fn main\(", re.M)
HARNESS = """

import std.fs
import std.process

fn main():
    args = process.args()
    data = fs.read_text(args[1]).value_or_panic()
    fuzz_target(data.as_str().as_bytes())
"""


def mutate(rng: random.Random, data: bytes, corpus: list[bytes], max_len: int) -> bytes:
    b = bytearray(data)
    for _ in range(rng.choice((1, 1, 1, 2, 3, 5))):
        kind = rng.randrange(9)
        if kind == 0 and b:
            i = rng.randrange(len(b))
            b[i] ^= 1 << rng.randrange(8)
        elif kind == 1 and b:
            b[rng.randrange(len(b))] = rng.randrange(256)
        elif kind == 2 and len(b) < max_len:
            b.insert(rng.randrange(len(b) + 1), rng.randrange(256))
        elif kind == 3 and b:
            del b[rng.randrange(len(b))]
        elif kind == 4 and b:
            i = rng.randrange(len(b))
            n = min(rng.randrange(1, 9), len(b) - i)
            del b[i:i + n]
        elif kind == 5 and len(b) < max_len:
            i = rng.randrange(len(b) + 1)
            b[i:i] = bytes(rng.randrange(256) for _ in range(rng.randrange(1, 9)))
        elif kind == 6 and b:
            val = rng.choice(INTERESTING)
            i = rng.randrange(len(b))
            b[i:i + len(val)] = val
        elif kind == 7 and len(b) > 1:
            i = rng.randrange(len(b))
            n = min(rng.randrange(1, 17), len(b) - i)
            j = rng.randrange(len(b) + 1)
            b[j:j] = b[i:i + n]
        elif kind == 8 and corpus:
            other = rng.choice(corpus)
            if other:
                i = rng.randrange(len(other))
                n = rng.randrange(1, min(32, len(other) - i) + 1)
                j = rng.randrange(len(b) + 1)
                b[j:j + n] = other[i:i + n]
    return bytes(b[:max_len])


class Runner:
    def __init__(self, exe: Path, workdir: Path, timeout: float) -> None:
        self.exe, self.dir, self.timeout = exe, workdir, timeout
        self.input = workdir / "input.bin"
        self.cov = workdir / "cov.txt"

    def run(self, data: bytes) -> tuple[bool, set[str]]:
        """(crashed, keys of statements executed). A timeout counts as a crash."""
        self.input.write_bytes(data)
        self.cov.unlink(missing_ok=True)
        env = dict(os.environ, GG_COV_OUT=str(self.cov))
        try:
            r = subprocess.run([str(self.exe), str(self.input)], capture_output=True, timeout=self.timeout, env=env)
            crashed = r.returncode != 0
        except subprocess.TimeoutExpired:
            return True, set()
        hit: set[str] = set()
        if self.cov.is_file():
            for line in self.cov.read_text(encoding="utf-8", errors="replace").splitlines():
                if line.startswith("H "):
                    parts = line.split()
                    if len(parts) == 3:
                        hit.add(parts[1])
                elif line.startswith("V "):
                    parts = line.split()
                    if len(parts) == 3:
                        hit.add(f"{parts[1]}#{parts[2]}")        # a new outcome or condition vector is progress too
        return crashed, hit


def shrink(runner: Runner, data: bytes) -> bytes:
    """A shorter input that still crashes: drop chunks, then single bytes."""
    best = data
    size = max(len(best) // 2, 1)
    while size >= 1:
        i = 0
        while i < len(best):
            trial = best[:i] + best[i + size:]
            if trial != best and runner.run(trial)[0]:
                best = trial
            else:
                i += size
        size //= 2
    return best


def cmd_fuzz(file: str, runs: int, seconds: float, seed: int, corpus_dir: str | None, crashes_dir: str,
             max_len: int, timeout: float, keep_going: bool, replay: str | None) -> int:
    src_path = Path(file)
    if not src_path.is_file():
        print(f"Error: no such file: {file}", file=sys.stderr)
        return 1
    source = src_path.read_text(encoding="utf-8-sig")
    if "fn fuzz_target(" not in source:
        print("Error: the file has no `fn fuzz_target(data: []u8)` to fuzz.", file=sys.stderr)
        return 1
    with tempfile.TemporaryDirectory(prefix="gg_fuzz_") as tmpname:
        tmp = Path(tmpname)
        harness = src_path.with_name(f".gg_fuzz_{src_path.stem}.gg")
        harness.write_text(_MAIN.sub("fn __gg_user_main(", source) + HARNESS, encoding="utf-8")
        exe = tmp / ("target.exe" if os.name == "nt" else "target")
        env = dict(os.environ, GG_COVERAGE="1", GG_COV_OUT=str(tmp / "build.cov"),
                   GG_COV_REMAP=f"{harness.resolve()}|{src_path.resolve()}")
        try:
            b = subprocess.run([sys.executable, "-m", "greengold", "build", str(harness), "-o", str(exe), "--release"],
                               capture_output=True, text=True, env=env)
        finally:
            harness.unlink(missing_ok=True)
        if b.returncode != 0 or not exe.is_file():
            print("Error: the fuzz target does not build:\n" + (b.stderr or b.stdout), file=sys.stderr)
            return 1
        runner = Runner(exe, tmp, timeout)
        if replay:
            crashed, _ = runner.run(Path(replay).read_bytes())
            print("crashed" if crashed else "ok")
            return 1 if crashed else 0
        rng = random.Random(seed)
        corpus: list[bytes] = []
        if corpus_dir:
            Path(corpus_dir).mkdir(parents=True, exist_ok=True)
        if corpus_dir and Path(corpus_dir).is_dir():
            corpus = [p.read_bytes() for p in sorted(Path(corpus_dir).iterdir()) if p.is_file()]
        if not corpus:
            corpus = [b"", b"\x00", b"A" * 8]
        seen: set[str] = set()
        findings = 0
        start = time.time()
        queue: list[bytes] = []
        for data in list(corpus):
            crashed, hit = runner.run(data)
            seen |= hit
            queue.append(data)
        done = len(corpus)
        while done < runs and (seconds <= 0 or time.time() - start < seconds):
            base = rng.choice(queue)
            data = mutate(rng, base, queue, max_len)
            done += 1
            crashed, hit = runner.run(data)
            if crashed:
                small = shrink(runner, data)
                name = hashlib.sha1(small).hexdigest()[:12]
                Path(crashes_dir).mkdir(parents=True, exist_ok=True)
                path = Path(crashes_dir) / f"crash-{name}"
                path.write_bytes(small)
                findings += 1
                print(f"FOUND  run {done}: {len(small)}-byte input saved to {path}")
                if not keep_going:
                    break
                continue
            if hit - seen:
                seen |= hit
                queue.append(data)
                if corpus_dir:
                    Path(corpus_dir).mkdir(parents=True, exist_ok=True)
                    (Path(corpus_dir) / hashlib.sha1(data).hexdigest()[:12]).write_bytes(data)
        elapsed = time.time() - start
        print(f"{done} runs in {elapsed:.1f}s, {len(seen)} coverage points, corpus {len(queue)}, findings {findings}")
        return 1 if findings else 0
