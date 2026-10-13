# Changelog

Greengold follows [semantic versioning](https://semver.org/) once it reaches 1.0. Until then, minor versions may contain breaking changes. See [`docs/STABILITY.md`](docs/STABILITY.md) for the editions and API-lock policy.

## 0.19.2

Borrow checker
- **Fix (soundness):** a view made in a branch of an `if` or `match` for a variable of the enclosing scope (`v = s.as_str()` when `v` held a literal) was forgotten after the branch, so `s.clear()` or a reassignment followed by a use of `v` was accepted, and so was a borrow carried to the next loop iteration behind an `if`. Both are now rejected (GG0316).
- Fewer false errors. GG0315 ("does not live long enough") is now decided where the owner's block ends: it fires only if the holder is still tied to the owner and is read again afterwards. `line = s.trim()` in a loop body, used only inside that body, is accepted; so is a view that is overwritten before the block ends, and a block that ends in `return`, `break`, or `continue`.
- `w.name = v` and `xs[i] = v` no longer count as a read of `w` / `xs`.
- The result of a call to a Greengold function is tied only to the arguments its `return` values can come from, not to every argument: `pick(a, b)` that returns `a` no longer holds on to `b`. A function whose returns cannot be read (an intrinsic) keeps the old rule.
- `tools/fuzz_views.py` is a soundness fuzzer: it generates random programs with views, loops, `break`/`continue`, `return`, lists, a struct field, `Optional[str]` and calls, runs every branch path in a model, and reports any program the checker accepts that uses a dangling view. On a random batch the false-error rate went from about 23 % to under 0.3 %, and no accepted program dangled in the last 40 000 programs.

## 0.5.0

Getting started
- `gg doctor` checks Python, LLVM, the linker, `PATH`, and the current package, and prints a fix for each problem.
- `gg repl` is an interactive prompt (declarations and bindings are kept; a bare expression is printed). `gg run -e CODE` runs a snippet without a file.
- `gg new --template bin|lib|cli` starts from a hello world, a library with tests, or a program that reads arguments.

Targets
- New target `wasm32-wasi` (`gg build --target wasm32-wasi`): a C library (wasi-libc), so `print`, strings, `List`, and `HashMap` work; the existing `wasm32` stays freestanding. Libc calls that take `size_t` go through 32-bit wrappers (`usize` stays 64 bits). It links with a sysroot named by `$GG_WASI_SYSROOT`. `std.thread`, `std.tasks`, and `std.net` report that they are unavailable there.

Website playground (`playground.html`)
- The compiler front end runs in the browser (Pyodide): live diagnostics, verified fixes, `fmt`, `gg explain`, and links that carry the code.
- **Run** compiles and runs the program in the browser: clang and lld as WebAssembly, `wasm32-wasi`, and a small WASI host with stdin, a 10 s limit, a Stop button, and Debug or Release.
- The editor colors code and compiler output, closes brackets and quotes, indents, comments lines (Ctrl+/), and completes words. A progress bar shows the start-up.
- For maintainers: `tools/build_playground.py` refreshes `website/playground/gg-bundle.zip` after compiler changes (a test checks it); `tools/fetch_llvm.py` fetches the LLVM files for self-hosting. The checklist is at the top of `website/README.md`.

## 0.4.2

Install and update
- Installers that need no Python: `installer/install.ps1`, `installer/install.sh`, and a Windows setup program; all put `gg` on `PATH`.
- `gg update` replaces the installed `gg` with the newest GitHub release (SHA-256 checked). **Breaking:** re-resolving dependencies is now `gg update --deps`.
- Release workflow builds `gg` for Windows x64, Linux x64/arm64, and macOS arm64 when a `v*` tag is pushed; the version comes from the tag. There is no Intel Mac build (no `llvmlite` wheel).
- VS Code extension runs `gg` (setting `greengold.path`, then `PATH`, then the installer folder) and falls back to `python -m greengold`; the release includes `greengold-vscode.vsix`.

Fixes
- Python 3.10: `tomli` is used where `tomllib` is missing.
- `gg build -g` on macOS runs `dsymutil`, so lldb finds lines and variables.
- Language server: a `file:///c:/dir` URI reads as `c:/dir` on every OS.
- `GG_LEAKCHECK`: the live-block counter is atomic, so threads no longer produce false leak reports.
- Benchmarks: `run_benchmarks.py` runs on Linux and macOS; the README lists what is needed to reproduce the numbers.
- Examples and tests no longer depend on tight wall-clock limits.

- Installers that need no Python: `installer/install.ps1`, `installer/install.sh`, and a Windows setup program; all put `gg` on `PATH`.
- `gg update` replaces the installed `gg` with the newest GitHub release (SHA-256 checked). **Breaking:** re-resolving dependencies is now `gg update --deps`.
- VS Code extension runs `gg` (setting `greengold.path`, then `PATH`, then the installer folder) and falls back to `python -m greengold`; the release includes `greengold-vscode.vsix`.
- Release workflow builds `gg` for Windows x64, Linux x64/arm64, and macOS arm64 when a `v*` tag is pushed.

## 0.3.3 (first public release)

Language
- Parameter modes `read` / `lend` / `consume` with inference for heap-owning parameters; `fixed` bindings with inference of unchanged variables.
- Structs, algebraic enums, exhaustive `match` with guards, tuples, generics with structural features, `dyn` features, operator overloading, const generics.
- Closures (`fn(...)` pointers and owned `Fn(...)` values), `async fn` / `await` on one thread (`std.tasks`), `defer`, `drop`, `comptime fn`.
- `Optional`, `Result`, and the `?` operator; `to_json` / `from_json` derive.

Compiler and tools
- LLVM backend (llvmlite, LLVM 22) with DWARF debug info, `--release` -O3, cross targets including `wasm32`.
- `gg run | build | check | fix | fmt | test | doc | api | bindgen | toolchain | lsp`.
- Language server and VS Code extension; verified fixes via `gg fix`.
- Links with the system C compiler or with `zig cc`; `tools/build_standalone.py` builds a single-file `gg`.

Standard library
- `std.collections`, `std.json`, `std.regex`, `std.http`, `std.net`, `std.thread`, `std.tasks`, `std.fs`, `std.time`, `std.rand`, and more.
