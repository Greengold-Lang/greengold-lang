# Benchmarks

Each workload is written three times, in Greengold (`.gg`), C++ (`.cpp`), and Rust (`.rs`), with the same
algorithm and the same output. `run_benchmarks.py` builds each one, runs it five times, and records the
median wall time, peak memory, compile time, and binary size. `reports/latest/` holds the newest
`benchmark_data.json`; the website is generated from that file.

## Reproduce the numbers

**You need**

| What | Why |
|---|---|
| Greengold (`gg` on `PATH`, see the [install](../README.md#install) section; or a source checkout with `pip install -e .`) | builds the `.gg` files with `--release`. `GG=/path/to/gg` picks another `gg`; with none found the script runs `python -m greengold` |
| Python 3.10+ and `pip install matplotlib` | the runner and the charts (`plotter.py`) |
| `g++` (GCC) | C++ builds with `-O3`. The published numbers use GCC, not clang |
| `rustc` (stable Rust) | Rust builds with `-C opt-level=3` (plain `rustc`, not `cargo build --release`) |
| A C compiler or `zig` for `gg build` | `gg toolchain` shows what was found; the standalone `gg` carries zig |
| For `gpumatmul` only: a GPU with an OpenCL driver | everything else runs without a GPU |

Windows, Linux, and macOS are supported by the runner. The published results are from Windows 11 with MinGW GCC;
`gg toolchain` and `g++ --version` and `rustc --version` print the versions to report next to your numbers.

**To get comparable numbers**

- Use the same flags: the runner does (`g++ -O3`, `rustc -C opt-level=3`, `gg build --release`).
- Plug in a laptop, close other programs, and let it cool between runs. Use `-n 9` to take the median of nine runs.
- Times include process start, and `primes` runs once because it is a fixed-length race.
- Expect different absolute times on other CPUs. Compare the ratios between the three languages, not the seconds.
- Peak memory is the working set on Windows and the maximum resident set on Linux and macOS; they are close but not the same measure.
- The runner overwrites `benchmark_results.json` and `reports/latest/`, even for one workload. Use `git checkout benchmarks/benchmark_results.json benchmarks/reports/latest/` to restore the published files.

**Run**

```bash
python benchmarks/run_benchmarks.py                     # every workload
python benchmarks/run_benchmarks.py wordfreq jsonparse  # some of them
python benchmarks/run_benchmarks.py -n 9                # nine runs each
```

Builds: `g++ -O3`, `rustc -C opt-level=3`, `gg build --release`. Times include starting the process.

## How to read the numbers

**Kernels vs. programs.** Most workloads are small numeric kernels (fib, mandel, nbody, matmul, ...). They
say how good the generated code is for a tight loop, not how fast a real program is. Three workloads look
more like programs: they allocate, use strings and hash maps, and recurse.

| Workload | What it does | Greengold opts out of checks? |
|---|---|---|
| `wordfreq` | builds a 3,000,000-word text, splits it, counts words in a hash map, sorts by count | no `trust`; `overflow: wrap` only in the random-number generator (Rust uses `wrapping_mul` there) |
| `jsonparse` | writes 200,000 records as 28 MB of JSON, parses them into a tree of values, walks the tree | no |
| `trees` | builds and walks 80 binary trees of 65,536 leaves (`Box` per node) | no |

**Checks that are switched off.** `--release` keeps bounds checks and traps on integer overflow. Several
kernels opt out where it matters: `trust xs[i]` skips one bounds check (only inside `unsafe:`), and
`overflow: wrap` makes arithmetic wrap. C++ never checks; Rust checks indexing unless the optimizer can
prove it safe and wraps on overflow in release builds. So a kernel that uses `trust` compares unchecked
Greengold with C++, not the default Greengold a user would write. `grep -c trust benchmarks/*.gg` lists them.

**fib.** Greengold beats GCC on `fib` because of one transformation. GCC inlines a small directly
recursive function into itself a couple of levels deep, and LLVM does not inline a function into itself.
Greengold (`greengold/recur_inline.py`) clones such a body twice before LLVM runs, so LLVM ends up doing what
GCC does. Rust, also on LLVM, keeps the plain recursion. The result says how one inlining decision works out,
and little about real programs.

**Hash maps.** `wordfreq` uses each language's standard hash map. Rust's default hasher is SipHash, which
resists hash flooding and is slower than the hashes C++ and Greengold use; with a faster hasher Rust would
be closer to C++.

**Measured on one machine.** The website lists the machine (Windows 11, Ryzen 5 5600X). Differences
under about 5% are noise there.

## Results for the program-like workloads

From one run on the machine above (2026-10-11, wall time of one run):

| Workload | C++ | Rust | Greengold |
|---|---|---|---|
| `wordfreq` | 0.19 s | 0.41 s | 0.24 s |
| `jsonparse` | 0.51 s | 0.45 s | 0.47 s |

C++ is still fastest on `wordfreq`. Both C++ and Greengold look each word up once (`counts[word]++`,
`counts.entry(word, 0) += 1`); the gap that is left is in hashing and splitting.

## GPU workload

`gpumatmul` runs a model the way inference does: 4096 token vectors of width 2048 go through 8 dense layers
on the GPU (f32 weights in -2..2, a tiled 16x16 matrix-product kernel, ReLU, and requantization to 0..127 as
in an int8 model). It uses OpenCL, loaded at run time (`OpenCL.dll`, `libOpenCL.so.1`, or the macOS
framework), so it needs a GPU driver with OpenCL and nothing else: no SDK, no headers, no extra library to
link. Every product is an integer below 2^24, so f32 is exact and every GPU prints `294743112 4035566 127`.

The kernel is the same OpenCL C text in all three languages, so the GPU part takes the same time everywhere.
What differs is the host side: generating the 33 million inputs and weights, uploading them, and driving the
queue. The Greengold version calls the OpenCL functions through function pointers read from the loaded
library (`ptr_read[fn(...) -> i32](addr(p))`), uses no `trust` and no `overflow: wrap`, and reserves its
lists up front with `reserve`, as the C++ (`reserve`) and Rust (`with_capacity`) versions do. Its counting
loop (`if v != 0: active += 1`) has no overflow check: the compiler sees that a counter started at 0 cannot
pass the loop's constant trip count (`greengold/counters.py`), and without the branch to a panic LLVM makes
the `if` branch-free. The sum next to it keeps its check, which is most of the gap to Rust.

From one run on the machine above with an RTX 3060 Ti (2026-10-11, median of nine runs, the process start
and the OpenCL compile included):

| Workload | C++ | Rust | Greengold |
|---|---|---|---|
| `gpumatmul` | 0.47 s | 0.46 s | 0.47 s |

## Not measured yet

- **An HTTP server.** Serving requests mostly measures the operating system's socket stack and needs a
  separate load generator. It is left out until both can run the same way on every platform.
- **Compile time** is measured by `compiler_speed.py`, not here.
