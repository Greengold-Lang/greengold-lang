# Greengold self-hosting plan

> **Status: frozen.** Self-hosting work was stopped at the `selfhost-freeze` tag (7f14867). The language will mature in the Python compiler first. `selfhost/` is not maintained; the parity tests run only with `GG_SELFHOST=1`. The plan below must be updated when work restarts.

This file holds the module map for moving the Python compiler to Greengold, the Python features it relies on, the stdlib gaps, and the chosen design. The language rules are in `docs/SPEC.md`. Line counts are physical lines (`str.splitlines`).

## Compiler modules

Total: **18490** lines of Python, 23 files, 725 functions, 116 classes. The core pipeline (lexer through codegen, excluding the CLI, LSP, and bindgen, and not counting the C99 backend) is about **13840** lines.

| File | Lines | Role |
|---|---:|---|
| `lexer.py` | 572 | `Token`, `Lexer`, `tokenize`. INDENT/DEDENT, keywords, escapes, indentation repair (`fmt.Layout`). |
| `parser.py` | 1877 | `Parser`, `parse`. Recursive descent. Backtracking with `ParseError`. Lambda lifting (named with `zlib.crc32`). |
| `ast_nodes.py` | 737 | Node data classes, `unparse`, `dump_ast`, `subst_self_func`. |
| `typeinfo.py` | 415 | Type predicates, mangling, `StructInfo` / `FuncInfo` / `VarInfo`. |
| `typecheck.py` | 3736 | `TypeChecker`, `MoveAnalyzer`, `check_program`, prelude loading. |
| `borrow.py` | 405 | `BorrowChecker`. Lifetimes of stored `read` / `lend`. |
| `matchcheck.py` | 369 | `MatchMixin`. Coverage and patterns. Close-name suggestions with `difflib`. |
| `generics.py` | 568 | `GenericsMixin`. Deduplication and monomorphization. |
| `comptime.py` | 350 | `Interp`. Constant folding. Special exceptions for control flow. |
| `diagnostics.py` | 410 | `Diagnostic`, `DiagnosticBag`, text and JSON rendering, patch application. |
| `codes.py` | 569 | The `GGxxxx` catalog and message classification. |
| `fmt.py` | 261 | The single layout. The lexer uses it for ambiguous indentation. |
| `codegen_llvm.py` | 2414 | `LLVMGen`. Builds IR with llvmlite and returns it as text. |
| `codegen_c.py` | 1706 | The deprecated C99 backend. |
| `llvm_driver.py` | 127 | IR verification, opt, object code, linking with `gcc`/`clang`. |
| `recur_inline.py` | 102 | Recursion copy in the release IR text. |
| `cli.py` | 743 | `argparse` subcommands, module loading, `build` / `run` / `check`. |
| `tools.py` | 287 | `gg.toml` (`tomllib`), test discovery, fmt, doc, SHA-256 cache. |
| `api.py` | 253 | The `gg api` catalog. |
| `lsp.py` | 2040 | Language server. Outside the component order; covered by the test suite. |
| `bindgen.py` | 540 | `extern` from a C header. Outside the component order. |
| `__init__.py`, `__main__.py` | 9 | Version and `python -m greengold`. |

Call order: `cli` reads the sources → `lexer.tokenize` → `parser.parse` → `typecheck.check_program` (which includes generics, match, borrow, move, comptime) → `codegen_llvm.generate_llvm` → `llvm_driver` object code and linker.

`selfhost/lexer.gg` is a lexer written earlier. On valid ASCII source its token text matches Python's. It does not carry diagnostic codes (`GGxxxx`), the indentation patch, or the edges of multi-line strings. During the port, the version that produces a diagnostic bag will replace it.

## Python features relied on

Counts are over `greengold/*.py`, measured with `ast`.

| Feature | Count | Self-host equivalent |
|---|---:|---|
| Dict literal `{}` | 411 | `HashMap`; the key must be copyable. An intern id (`usize`) for owned text. |
| Set literal | 42 | `HashSet`, same constraint. |
| `dict` / `set` calls | 19 / 41 | Same. |
| Indexing | 1754 | POD nodes in an arena, and `List[T]` (when `T` is not heap-owning). |
| f-string | 1139 | `string` builder and `append_*`. |
| `isinstance` | 696 | `match` or a tag field. The AST node will be a tagged POD, not an enum. |
| `getattr` / `hasattr` | 298 / 10 | Fields live on the struct; no dynamic attributes. |
| Direct recursion | 107 | Function recursion. The stack is enough for deep syntax trees; TCO is not needed. |
| Method recursion | 143 | Same. 53 separate functions call themselves (`_expr`, `_stmt`, `eval`, `needs_drop`, `mangle`, ...). |
| `raise` | 130 | `ParseError` backtracking in the parser. In Greengold a diagnostic list + `Result`; no exceptions. |
| `try` / `except` | 46 / 45 | `Result` / `Optional` and `?`. |
| List / dict / set comprehension | 109 / 14 / 9 | `for` + `List.push`. |
| Generator expression | 129 | Same. `yield` appears 7 times, mostly in generator expressions. |
| lambda | 21 | A local function or a plain loop. |
| `copy.deepcopy` | 16 | Copying nodes in the arena (a field copy, since they are POD). |
| `re` | 7 files, ~60 calls | Manual scanning. A regex engine will not be added. |
| `json` | 6 calls | A small JSON writer (diagnostics and the test report). Parsing only in the LSP body. |
| `subprocess.run` | 4 | `std.process.process_run`. |
| `Path.read_text` / `write_text` | 8 / 12 | `std.fs.read_file_to_string`, `write_string_to_file`. |
| `zlib.crc32` | 1 | A file hash used in the lambda name. FNV or the same polynomial; there is no zlib in the stdlib. |
| `hashlib.sha256` | 1 | The cache key. The content hash lives in the compiler. |
| `tomllib` | 1 | A small reader for `gg.toml`. |
| `difflib` | 3 | Close-name suggestions. A short Levenshtein. |
| `argparse` | 1 | The CLI parses by hand. |
| `tempfile` | 2 | A temporary directory for running. |
| `dataclasses` | 10 files | `struct`. A copyable struct instead of a frozen token. |
| llvmlite | 3 files | Text IR + the system `clang`/`gcc`. No new Python dependency. |

The file and process side lives in `cli.py`, `llvm_driver.py`, `tools.py`, and `lsp.py`. Dictionaries and recursion are in every front-end module. The exceptions are in the parser (`ParseError`), comptime (`_Return`, `_Break`, `_Continue`, `_Yield`), and the LLVM driver (`LLVMError`, `CodegenError`, `CompileError`).

## What to add to the stdlib first

Existing equivalents:

- **String.** `string` in `core` and `std.string` (search, trim, lines, number parsing, `append_*`) are enough for this job. `panic` still takes only a constant string; dynamic messages go through `Result` or `print`.
- **Dynamic array.** `List[T]` exists. Indexing is forbidden when the element is heap-owning (`string`, `List`, `Box`) (`typecheck.py`). `get` returns a view, but loading the heap header is a shallow copy. In the compiler's lists the element will be POD (a number, `bool`, an id).
- **Hash map.** `std.collections.HashMap` and `HashSet` exist. The key and value must be copyable. `string` is not copyable. `str` is a view; when the backing `List` grows, the pointer dangles. The map key will be an intern id.
- **File reading/writing.** `read_file_to_string`, `write_string_to_file`, `file_exists`, `remove_file` exist. Byte-by-byte `fgetc` is slow but good enough for compiler sources.
- **Process.** Only `process_exit` and `env_get`. There is no call that runs the linker.
- **Error carrying.** `Optional`, `Result`, and `?` exist. A diagnostic list takes the place of the parser exception. No new type is needed under this heading.

The gaps, each a separate `stdlib:` commit with an end-to-end test. **Status (2026-10-10): all five are done** (`std.process` `args`/`process_run`, `eprint`, `std.fs` path and directory operations, `std.intern`; see `docs/SPEC.md` §16). The list stays as history:

1. **`std.process.args() -> List[str]`.** `fn main():` takes no parameters. The generated LLVM `main` is today `i32 @main()` and drops `argc`/`argv`. First a small `lang:` change: execution becomes `main(i32, i8**)`, stores the count and the pointers, and produces `gg_argc` / `gg_argv`. Then the stdlib turns these two into a `List[str]`. `docs/SPEC.md` §16 is updated.
2. **`std.process.process_run`.** Takes an argument list. Returns the exit code, standard output, and standard error. `None` if the process cannot be started. `CreateProcessA` and a pipe on Windows, `fork` / `execvp` / `pipe` on POSIX. `system` is not enough: today a link error is printed from the child's stderr.
3. **stderr.** `print` writes only to stdout (`printf`). Diagnostics must go to stderr. `eprint` uses `fprintf(stderr, ...)` with the same call shape. It is a built-in; a runtime matter, not syntax. It is added to the SPEC builtin list (together with `lang:`, no stdlib wrapper is needed).
4. **Path and directory (`std.fs`).** `path_join`, `path_parent`, `path_name`, `path_ext` are string operations. `make_dir`, `list_dir`, `rename_file` are needed for imports, `gg test`, and `.gg-cache`.
5. **Stable string interning (`std.intern`).** `intern(text) -> usize` pins the text once with `malloc`; the id is a copyable map key. Storing a `str` into a growing `string` buffer breaks on reallocation. The compiler symbol table depends on this.

What stays inside the compiler (no separate stdlib module is opened): the JSON writer, the TOML subset, FNV/SHA-256, Levenshtein, crc32 for the lambda name. No regex is added.

## Design

The externally visible behavior stays the same: the token sequence, the AST dump, the `GGxxxx` code, the `gg check` text and `--json`, the stdout/stderr and exit code of `gg run`.

Internally, the Python object graph is not copied.

- The source text lives as one `string`. A token and a node carry `(file, start, end)`.
- The AST is an arena of copyable records. Children are `usize` ids. The tag is a `u8` field; it replaces the `isinstance` chain.
- The symbol table is a `HashMap[usize, usize]` (intern id → arena record).
- Diagnostics live in a `List`. On an error the parser returns a node id; it does not unwind the stack.
- Code generation writes text LLVM IR. The system `clang` or `gcc` is called for optimization and object code. llvmlite is not ported to the Greengold side. This is the same compiler that serves as the linker today; it is not a new dependency.
- The IR has no timestamps, no absolute paths, and no hashmap iteration order. `HashMap` keeps insertion order; the dump is still sorted by id.
- stage2 and stage3 compile the same sources with the same compiler. For the binaries to be identical, `-ffile-compilation-dir=.` and the flags that turn off timestamps are used on the `clang` side. If a difference remains, the nondeterminism in the compiler output is removed; the test is not loosened.

Component order: stdlib gaps, then lexer, parser and AST, type and ownership (typecheck, borrow, match, generics, typeinfo, diagnostics, codes, comptime), code generation, CLI. `fmt` comes with the lexer because the indentation patch depends on it. The LSP and bindgen wait until the CLI behavior passes the language part of the test suite without them. The `gg lsp` Python tests call `greengold.lsp` in process; binary verification goes through `scripts/selfhost_diff.py` and `scripts/bootstrap.sh`.

## Differential test

`tests/selfhost_diff/` keeps that the Python version and the Greengold version write the same output for the same input. The input set:

- source fragments and `must_fail` examples in `tests/`
- `docs/SPEC.md` code blocks
- `examples/*.gg` and `greengold/std/*.gg`, `greengold/core/core.gg`

What is compared: token lines, the AST dump, diagnostic code + message, `check --json`, and the stdout/stderr/exit code of a compiled program. No commit if the diff file is not empty.

## Verification

`scripts/bootstrap.sh` (on Windows the same steps in `bootstrap.ps1`):

- stage1 = the Greengold compiler produced by the Python compiler
- stage2 = the compiler produced by stage1
- stage3 = the compiler produced by stage2
- stage2 and stage3 are identical byte for byte
- all three pass the language test suite
- time and binary size are written to `SELFHOST_REPORT.md`

## Test baseline

`python -m pytest -q --tb=line` (9 October 2026, Windows): **769 passed, 60 skipped**, 141.33 seconds. No red tests. Branch: `selfhost/main`.
