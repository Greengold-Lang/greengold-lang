# Changelog

Greengold follows [semantic versioning](https://semver.org/) once it reaches 1.0. Until then, minor versions may contain breaking changes. See [`docs/STABILITY.md`](docs/STABILITY.md) for the editions and API-lock policy.

## Unreleased

Getting started
- `gg doctor` checks Python, LLVM, the linker, `PATH`, and the current package, and prints a fix for each problem.
- `gg repl` is an interactive prompt (declarations and bindings are kept; a bare expression is printed). `gg run -e CODE` runs a snippet without a file.
- `gg new --template bin|lib|cli` starts from a hello world, a library with tests, or a program that reads arguments.
- Website playground (`playground.html`): the compiler front end runs in the browser through Pyodide, with live diagnostics, checked fixes, `fmt`, and `explain`; **Run** compiles and runs the program in the browser (clang and lld as WebAssembly, `wasm32-wasi`, a small WASI host with stdin and a 10 s limit). `tools/fetch_llvm.py` fetches the toolchain for self-hosting.
- New target `wasm32-wasi` (`gg build --target wasm32-wasi`): a C library, so `print`, strings, `List`, and `HashMap` work. Libc calls that take `size_t` go through 32-bit wrappers (`usize` stays 64 bits). `std.thread`, `std.tasks`, and `std.net` report that they are unavailable there. After changing the compiler, run `python tools/build_playground.py` to refresh `website/playground/gg-bundle.zip` (a test checks it).

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
