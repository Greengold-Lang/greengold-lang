# Third-party files in the playground

* `llvm-glue.js` is `shared.js` from https://github.com/binji/wasm-clang (Copyright 2020 WebAssembly Community Group
  participants, Apache License 2.0), unmodified. The `clang` and `lld` WebAssembly builds that `tools/fetch_llvm.py`
  downloads are from the same project: LLVM 8 under the Apache License 2.0 with LLVM exceptions.
* `wasi/libc.a`, `wasi/crt1.o`, and `wasi/libc.imports` are wasi-libc (MIT, Apache 2.0 with LLVM exceptions, and
  the licenses of its musl and CloudABI parts), taken from the same project's sysroot.
  `wasi/libclang_rt.builtins-wasm32.a` is compiler-rt (Apache 2.0 with LLVM exceptions).
* Pyodide (MPL 2.0) loads from the jsDelivr CDN at run time.
