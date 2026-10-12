# Changelog

Greengold follows [semantic versioning](https://semver.org/) once it reaches 1.0. Until then, minor versions may contain breaking changes. See [`docs/STABILITY.md`](docs/STABILITY.md) for the editions and API-lock policy.

## Unreleased

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
