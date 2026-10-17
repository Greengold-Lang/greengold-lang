# Changelog

Greengold follows [semantic versioning](https://semver.org/) once it reaches 1.0. Until then, minor versions may contain breaking changes. See [`docs/STABILITY.md`](docs/STABILITY.md) for the editions and API-lock policy.

## Unreleased

- **`--cpu` and `--features`** for `build`, `run`, `emit-ll` and `emit-bc` (and `GG_CPU`, `GG_FEATURES`): `--cpu native` makes code for the CPU that runs the compiler, `--cpu haswell` / `x86-64-v3` / `apple-m1` for a named one, `--features +avx2,+fma,-avx512f` adds or removes features. Without them the code still runs on any CPU of the target. It works with the built-in LLVM and with an outside clang, and is part of the build cache key.
- SIMD: `fma` on float vectors, `dot_i8` / `dot_u8i8` (the int8 multiply-add of quantized matrix products; `pmaddwd` on x86), and the vector types `i8x16`, `i8x32`, `u8x32`. New benchmark `qmatvec` (int8 matrix-vector product).
- New `std.parallel`: `Pool.new(threads)` and `pool.for_range(n, f, ctx)` share the range `0..n` between a pool of worker threads (the calling thread takes part). New benchmark `qmatvec_mt` (the same product on all CPUs).
- New `std.tensor`: `Tensor`, the ggml-compatible blocks `BlockQ8` (`q8_0`) and `BlockQ4` (`q4_0`), `Q8Vec`, `Q4Matrix` / `Q8Matrix` with `matvec` and `matvec_parallel`, 16-bit float conversion. SIMD: `shr`, `shl`, `as_i8` / `as_u8`, `to_f32`, `join`, and `dot_u4i8` (4-bit data). The `std.tensor` matrix kernels use 256-bit steps, two rows at a time, and scales converted once per vector block (`q4_0` 4096x4096 product: 1.5 ms to 0.75 ms on one thread with `--cpu native`). Without `--cpu native` the 256-bit vectors are emulated and these kernels run several times slower. New benchmark `q4matvec`.
- New `std.mmap` (`MappedFile`, read-only memory-mapped files) and `std.gguf` (`Gguf.open` reads GGUF model files: metadata, tensor table, and zero-copy `q4_blocks` / `q8_blocks` / `f32_values` views). New intrinsic `slice_from_raw[T](p, len)`. `std.tensor` gains `q4_matvec`, `q8_matvec` (and `_parallel`) on block views and `dequantize_row_q4` / `_q8`.

## 0.22.0

- `std.http` speaks **https**: `http.get("https://...")` checks the server's certificate against the system's trusted roots and the host name, so an expired, self-signed, or wrong-host certificate is an error. TLS is the system's SChannel on Windows and OpenSSL (`libssl`) on Linux and macOS; the linker adds `-lssl -lcrypto` only to programs that use it, and a Windows program is linked with `-lsecur32`. New `std.tls` (client only).
- **Time limits.** `TcpStream.set_timeout(ms)` and `UdpSocket.set_timeout(ms)` limit every later send and receive (`Err("timed out")`, tested with `net.is_timeout(e)`; the stream stays usable). `TcpStream.connect_timeout`, `connect_tls`, `TcpListener.accept_timeout`. `http.get_timeout(url, ms)` and `http.fetch(method, url, body, opts)` with `http.options()` (`timeout_ms`, 30 seconds by default, `max_redirects`, `max_body`, `header(name, value)`). `http.serve` now drops a client that is silent for 10 seconds (`http.serve_with` sets the time).
- The http client follows redirects, reads `Transfer-Encoding: chunked` bodies and bodies sent with `Content-Length`, and sends `User-Agent`. Host names are looked up (`std.net` used to take only IPv4 digits and `localhost`).
- **Networking for game servers.** `net.Poller` waits for many sockets at once (`wait(ms)` returns the ready ones), with `TcpListener.try_accept`, `TcpStream.try_receive`, `send_some`, `readable`, `UdpSocket.receive_from_try`, `reply`, `set_broadcast`, `set_buffers`, `peer_addr`, `set_nodelay` (TCP sockets now start with `TCP_NODELAY` on), and non-blocking mode. Messages: `send_frame` / `receive_frame` and the new `std.packet` (`ByteWriter`, `ByteReader`, `FrameBuffer`). A write to a closed connection is an `Err` on Linux and macOS, not SIGPIPE, and Windows no longer reports an earlier ICMP "port unreachable" as a receive error on a UDP socket.
- New `std.sock` (`wait`, `poll_many`) shared by `std.net` and `std.tls`.

- Block comments: `#[ ... ]#` spans several lines or sits inside a line, and nests (`#[ a #[ b ]# c ]#`). An unclosed one reports `Unterminated block comment.` `gg fmt` leaves the inside of a block comment untouched. The VS Code grammar and the playground highlighter know the new form.

## 0.21.5

- The body of an `attribute` can call `str` methods at compile time: `len()`, `is_empty()`, `starts_with(p)`, `ends_with(p)`, and `contains(p)`. Any other method now says it cannot be called at compile time instead of "unsupported expression".
- `print(...)` works in an `attribute` body. It is shown as a note (`GG0410 attribute-print`) at the `@name` line, never fails the build, and appears in `gg check --json` as a `note`.
- `docs/API.md` is the standard library reference, generated from the library source by `tools/build_api_docs.py` (a test keeps it current). It also covers what the catalog cannot: attributes (what the body can read, the `gg attrs` JSON), the compiler intrinsics, and the JSON output of each command.

## 0.21.4

- `gg update` no longer leaves `gg` broken when a file is in use: the rollback restores every file, and the Windows finish step keeps the old `_internal` until the copy has succeeded. It also prints each step (verifying, unpacking, checking, installing) instead of going silent.

## 0.21.3

- The language server completes `import`: type `import ` for the standard library, dependencies and local files, `import std.` for the modules inside `std`, or `import "` for file paths. It reads only the folder you have typed so far.
- The standalone `gg` is a folder (`gg` next to `_internal`) instead of one file, so it starts at once. The one-file build unpacked about 150 MB into a temp folder on every run, which took 10 to 25 seconds for `gg --version` on Windows. Release assets are now `gg-windows-x64.zip` and `gg-<os>-<arch>.tar.gz`; the installers and `gg update` handle them. This release also still carries the old one-file names (`gg-windows-x64.exe`, `gg-linux-x64`, ...) so that `gg update` of 0.21.0 and older can fetch it; run `gg update` once more afterwards to move to the folder install.

## 0.21.0

- New standalone extension **Greengold Themes** (`greengoldlang.greengold-themes`, folder `vscode-themes/`): the Greengold Dark and Greengold Light color themes, installable on their own and published to the VS Code Marketplace and Open VSX with each release. `greengold-vscode` still includes them.
- An `attribute` can have a body: `attribute range(min: int, max: int) on field:` followed by `comptime` code that runs once for each use, sees the arguments and `target_kind`, `target_name`, `target_owner`, `target_type`, and calls `compile_error(message)` to reject the use. New code GG0409.
- `docs/STABILITY.md` is rewritten as a stability policy: what is promised before 1.0 and from 1.0, the exceptions (soundness and compiler bugs), deprecation, editions at most every three years, and which tool interfaces are covered.
- Benchmarks: all workloads are measured again with stable Rust 1.97.1. `particle` now uses a structure of arrays in C++ and Rust as well, so it compares compilers and not memory layouts. `primes` no longer needs a Windows-only timer.

## 0.20.0

Attributes and VS Code
- `@name(args)` above a `fn`, an `impl` method, a `struct`, or a field, declared first with `attribute name(param: kind) on fn, struct, field`. The compiler checks each use and gives it no behavior; `gg attrs file.gg` lists the uses as JSON for code generators (RPC stubs, serialization tables). New codes GG0407 and GG0408.
- VS Code extension: highlighting for `attribute` declarations and `@name(...)` lines, snippets (`attribute`, `attr`, `attrreplicated`), and completion of the declared attributes after `@`.

Thread safety
- **Fix (soundness):** `std.tasks` kept one scheduler for the whole program, so two threads that each used `async`/`await` corrupted it (a crash in safe code). The first thread to use tasks now owns them, and a call from another thread stops the program with "tasks belong to one thread".
- **Fix (soundness):** a view taken through a call that returns a reference (`v = g.value().as_str()` with `g` a `Locked` guard) was not tied to its owner, so it could outlive the guard and read memory another thread had freed. It is now tied to `g` (GG0315 / GG0316).
- `std.net` started the Windows socket library with a plain flag: a second thread could use sockets before the first had finished `WSAStartup`. One thread now starts it and the others wait.
- `tools/fuzz_threads.py` runs programs whose threads overlap (`Arc[Locked[T]]`, `Queue`, atomics, read-only `Arc`) under the memory oracle; `tools/send_matrix.py` checks the rule for what may cross a thread against a hand-written table (152 cases, no hole, no false error).

## 0.19.2

Borrow checker
- **Fix (soundness):** a view made in a branch of an `if` or `match` for a variable of the enclosing scope (`v = s.as_str()` when `v` held a literal) was forgotten after the branch, so `s.clear()` or a reassignment followed by a use of `v` was accepted, and so was a borrow carried to the next loop iteration behind an `if`. Both are now rejected (GG0316).
- Fewer false errors. GG0315 ("does not live long enough") is now decided where the owner's block ends: it fires only if the holder is still tied to the owner and is read again afterwards. `line = s.trim()` in a loop body, used only inside that body, is accepted; so is a view that is overwritten before the block ends, and a block that ends in `return`, `break`, or `continue`.
- `w.name = v` and `xs[i] = v` no longer count as a read of `w` / `xs`.
- The result of a call to a Greengold function is tied only to the arguments its `return` values can come from, not to every argument: `pick(a, b)` that returns `a` no longer holds on to `b`. A function whose returns cannot be read (an intrinsic) keeps the old rule.
- `tools/fuzz_views.py` is a soundness fuzzer: it generates random programs with views, loops, `break`/`continue`, `return`, lists, a struct field, `Optional[str]` and calls, runs every branch path in a model, and reports any program the checker accepts that uses a dangling view. On a random batch the false-error rate went from about 23 % to under 0.3 %, and no accepted program dangled in the last 40 000 programs.
- **Fix (soundness):** `a[i] = v` after `a` was moved (`b = a`) was accepted and dropped the old element twice (double free). It is now a use of a moved value (GG0301).
- Memory-safety oracle (`tools/safety_oracle.py`, `tools/fuzz_safety.py`, `tools/fuzz_typed.py`): programs are built with a checking `allocator` and run twice (freed memory kept / freed memory poisoned). A difference means a read of freed memory; bad frees, writes after free, heap overflows, and blocks still live at a clean exit are reported too. A 6 000-program typed run found one double free (fixed above) and no use-after-free. Fuzzing finds violations; it does not prove there are none.

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
