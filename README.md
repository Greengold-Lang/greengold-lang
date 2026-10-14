# Greengold

> **The normative language reference is [`docs/SPEC.md`](docs/SPEC.md).** When this file and the spec disagree, the spec wins.
>
> 📖 **Tutorial:** a step-by-step guide that teaches Greengold from scratch is in the [Learn/ series](Learn/Introduction.md).
>
> 💬 **Community:** questions, feedback and chat happen on [Discord](https://discord.gg/sp65habzne).

**Greengold** is an indentation-sensitive, memory-safe systems programming language. It aims at C++/Rust speed with a gentle learning curve: ownership and borrowing are checked at compile time without lifetime annotations, and the parameter mode is written once, on the signature.

The `greengold` package compiles `.gg` files to **LLVM IR** (via `llvmlite`), then to machine code, and links with the system `gcc`/`clang`, or with `zig cc` when neither is installed (`pip install greengold[toolchain]` brings zig, which also links for every `--target`). Dependencies: Python 3.10+ and `llvmlite` 0.50 or newer, which carries LLVM 22 (`pytest` for tests). The LLVM that turns the IR into machine code is the one inside llvmlite, or one you pick: `GG_BACKEND=clang` uses `clang` 15 or newer from PATH, and `GG_LLVM` names another (a path to a clang, or `zig` for the clang inside Zig). With an older llvmlite and no `GG_BACKEND`, a newer outside clang is used when one is found. `gg toolchain` shows what was found. `python tools/build_standalone.py` (with PyInstaller) builds `dist/gg`, the whole compiler as one file that needs no Python; with `ziglang` installed it bundles zig too.

```gg
const MASK: u32 = 0xFF

fn sum(a: []i32) -> i32:
    total = 0
    for x in a:
        total += x
    return total

fn main():
    nums = [10, 20, 30, 40]
    print("Total:", sum(nums))
    print("Mask:", MASK & 0x0F)
```

---

## Status

Greengold is **pre-1.0 and experimental** (version 0.21.x). The language, the standard library, and the diagnostics can still change between minor versions; [`docs/STABILITY.md`](docs/STABILITY.md) describes editions and the API lock check. Do not use it for anything that must be correct yet.

Known limits:

- **Platforms.** Development and testing happen mainly on Windows. CI runs the test suite on Windows, Linux, and macOS (Apple Silicon); Windows gets the most use, so Linux and macOS may still show differences. The POSIX implementation of `async fn` (`std.tasks`, `ucontext`) and linking through a real `zig cc` have had little testing. Sockets use `poll` / `WSAPoll`, not epoll, kqueue, or IOCP.
- **Function pointers** (`fn(...)`) cannot take heap-owning parameters; use a feature bound or an owned `Fn(...)` closure.
- **Not implemented:** a MIR / control-flow layer under the borrow checker, and lifetime tracking of stored views beyond the rules in the spec.
- The compiler is written in Python. It starts fast, but compile times on large programs are slower than a native compiler.

Bug reports are welcome; see [CONTRIBUTING.md](CONTRIBUTING.md).

---

## Install

No Python needed. The installers download the `gg` archive for your platform from the
[latest release](https://github.com/Greengold-Lang/greengold-lang/releases/latest), check its SHA-256, and add it to your `PATH`.
The install is a folder (`gg` and `_internal`) with the compiler, LLVM, and Zig, so `gg build` links programs without a C compiler installed.

**Windows** (PowerShell), or download `gg-setup-windows-x64.exe` from the release page:

```powershell
irm https://raw.githubusercontent.com/Greengold-Lang/greengold-lang/main/installer/install.ps1 | iex
```

**Linux and macOS:**

```bash
curl -fsSL https://raw.githubusercontent.com/Greengold-Lang/greengold-lang/main/installer/install.sh | sh
```

Open a new terminal and run `gg --version`. Builds exist for Windows x64, Linux x64 and arm64, and macOS on Apple Silicon (arm64). There is no Intel Mac build, because `llvmlite` has no wheel for it; on an Intel Mac, run from source with `pip install -e .`.
`GG_VERSION=0.3.3` picks a version, `GG_INSTALL_DIR` the folder, `GG_NO_MODIFY_PATH=1` leaves `PATH` alone.

**Update:** `gg update` downloads the newest release, verifies it, and replaces the installed `gg` (`gg update --check` only looks;
`gg update --tag 0.3.3` installs a given version). To re-resolve a package's dependencies, use `gg update --deps`.
`gg update` works on the standalone install only; with `pip install` use `pip install -U git+https://github.com/Greengold-Lang/greengold-lang.git`.

**Uninstall:** delete the folder (`%LOCALAPPDATA%\Greengoldin` or `~/.greengold/bin`) and its `PATH` entry, or use "Apps" on Windows if you used the setup program.

---

## How to Run

```bash
pip install -e .                                     # from a source checkout (see Install for the no-Python way)
gg run   examples/numeric.gg                         # compile + run (debug)
gg run   examples/numeric.gg --release               # compile + run (LLVM -O3)
gg run   examples/rpg/main.gg                        # multi-file project (resolves imports)
gg build examples/arrays.gg -o arrays                # build an executable
gg check examples/arrays.gg --json                   # diagnostics only, as JSON
gg fix   .                                           # apply the compiler's verified fixes (--likely, --dry-run)
gg emit-ll examples/arrays.gg                        # LLVM IR (optimized with --release)
gg test  .                                           # run `test` blocks and `fn test_*()`
gg fmt   .                                           # canonical layout
gg explain GG0301                                    # explain an error code
gg toolchain                                         # LLVM version, linker, zig, debuggers found
gg doctor                                            # check this machine and package, with a fix for each problem
gg repl                                              # interactive prompt (or: gg run -e "6 * 7")
gg new hello --template cli                          # bin (default), lib, or cli
gg update                                            # update gg to the newest release
```

`python -m greengold <command>` works without installing.

| Flag (`build`, `run`) | Meaning |
|---|---|
| `--release` | LLVM `-O3`. Bounds, overflow, division and shift checks stay on. |
| `--unchecked` | UNSAFE: removes array/slice/string bounds checks. |
| `-o <name>` | Output file (`build`). |
| `--link <lib>`, `-L <dir>`, `--link-file <file>` | Linker inputs, see [FFI](#calling-c-and-rust-ffi). |
| `--no-std` | No libc/OS: Core library only (no `print`, `input`, heap). |
| `--target <triple\|bare-metal>` | Target triple; `bare-metal` writes an `x86_64-unknown-none-elf` object file. |

Other commands: `new`, `doc`, `api`, `bindgen`, `lsp`, and the debug dumps `tokens` and `ast`.

---

## The Language at a Glance

Each line links to the spec section with the full rules.

- **Bindings** ([§3](docs/SPEC.md#3-bindings)): `x = 1` can be changed; `fixed x = 1` never changes. A variable that nothing changes is treated as `fixed` (the editor shows the word as a hint). No global variables.
- **Types** ([§2](docs/SPEC.md#2-names-types-and-literals), [§12](docs/SPEC.md#12-numbers)): `i8`…`i64`, `u8`…`u64`, `isize`, `usize`, `f32`, `f64`, `bool`, `str` (text view), `string` (owned text), `[N]T`, `[]T`, `T in lo..hi`. No implicit conversions: `i64(x)`.
- **Integer overflow traps** in debug and release. `wrapping_*`, `checked_*`, `saturating_*`, and `wrapping:` blocks opt out.
- **Parameter modes** ([§4](docs/SPEC.md#parameter-modes)): `p: T` copies, `p: read T` shares, `p: lend T` borrows exclusively, `p: consume T` takes ownership. The call is always `f(x)`. For a heap-owning parameter the mode can be left out: the compiler infers `read`, `lend`, or `consume` from the body.
- **Copy and move** ([§5](docs/SPEC.md#5-copy-and-move)): numbers and plain structs copy; `Box`, `List`, `string` and anything holding them move, and are freed at scope exit. `x.clone()` makes a deep copy.
- **Structs, enums, `match`** ([§7](docs/SPEC.md#7-structs-methods-enums)): methods live in `impl Type:`; `match` is exhaustive.
- **Generics and features** ([§8](docs/SPEC.md#8-generics-and-features)): monomorphized; features are structural (Go-style) bounds.
- **Errors** ([§9](docs/SPEC.md#9-optional-result-and-)): `Optional[T]` (`Valid`/`None`), `Result[T, E]` (`Ok`/`Err`), and `?`.
- **Heap and text** ([§10](docs/SPEC.md#10-heap-text-arrays-slices)): `Box[T]`, `List[T]` (elements are places: `grid[i].push(x)`), `string`, and the reference-counted, read-only `Shared[T]`; slices are parameters only.
- **References** ([§11](docs/SPEC.md#11-references)): `read place` / `lend place`, `-> ref T`, no lifetime annotations.
- **Lambdas and closures** ([§13](docs/SPEC.md#13-expressions)): `fn(x: i32) -> i32 => x + k` may capture variables; passing a closure to a `fn(...)` parameter compiles a direct call. `Fn(A) -> R` is an owned closure value that can be returned and stored.
- **Compile time** ([§14](docs/SPEC.md#14-constants-and-compile-time-functions)): `const`, `comptime fn`.
- **Modules** ([§16](docs/SPEC.md#16-imports-and-the-library)): `import "file.gg"`, `import std.name`, `public` / `private` sections (a file starts public).

```gg
struct Counter:
    value: i32

impl Counter:
    fn bump(self: lend Self):
        self.value += 1

enum Shape:
    Circle(f64)
    Rect(f64, f64)

fn area(s: Shape) -> f64:
    return match s:
        Circle(r) => 3.14159 * r * r
        Rect(w, h) => w * h

fn parse_digit(c: u8) -> Result[i32, str]:
    if c >= '0' and c <= '9':
        return Ok(i32(c - '0'))
    return Err("not a digit")

fn main():
    c = Counter{ value: 0 }
    c.bump()
    xs = List[f64]()
    xs.push(area(Shape.Circle(1.0)))
    xs.push(area(Shape.Rect(2.0, 3.0)))
    print(c.value, xs.len, xs[1])
    match parse_digit('7'):
        Ok(d):
            print(f"digit {d}")
        Err(e):
            print(e)
```

---

## Runtime Checks

A failed check stops the program with exit code **101** and a diagnostic on stderr:

```
Runtime error: array index out of bounds (index 5, length 3)
  --> file.gg:4:11
```

Checked in debug **and** `--release`: array/slice/string indexing, slice ranges, integer `+ - *` overflow, division and modulo by zero, `MIN / -1`, and shift amounts outside `0..width`. Only `--unchecked` removes the bounds checks; out-of-bounds access is then undefined behavior. `GG_LEAKCHECK=1` reports unfreed heap blocks at exit.

---

## Calling C and Rust (FFI)

```gg
extern "math.h" fn sqrt(x: f64) -> f64

fn main():
    print(sqrt(2.0))
```

* The header name after `extern` documents where the symbol comes from; the function is declared directly in LLVM IR and resolved by the linker.
* Parameters: numeric, `bool`, `str` (passed as a NUL-terminated `char*`), `read`/`lend` structs (`T*`), raw pointers, and function pointers. Returns: numeric, `bool`, pointer, or nothing. Slices, arrays, `consume` parameters, and structs by value are rejected.
* Working examples: [`examples/ffi/`](examples/ffi) (`c/`, `rust/`, `pointers.gg`).

| Linker flag | Meaning |
|---|---|
| `--link name` | `-lname` |
| `-L dir` / `--link-path dir` | Library search directory |
| `--link-file file` | Link `.a`, `.o`, `.lib`, `.so`, `.dll` directly |
| `GG_LINK_ARGS` (env) | Raw flags passed to the linker |

**Raw pointers and `unsafe`.** `*T`, `*mut T`, `*void`, and `null` exist for FFI. Reading or writing through a pointer, `addr` / `addr_mut`, `ptr_cast`, `ptr_offset`, `ptr_to_int` / `int_to_ptr`, and `cstr_to_string` / `string_to_cstr` need an `unsafe:` block; the compiler does not check pointer validity there. See [SPEC §15](docs/SPEC.md#15-foreign-functions-and-pointers).

**Rust.** Export with `#[no_mangle] pub extern "C" fn ...`, build a `staticlib` (`panic = "abort"`), and link it with `--link-file libxxx.a`, adding the system libraries that `cargo rustc --release -- --print native-static-libs` lists via `--link`. On Windows use the `x86_64-pc-windows-gnu` target. Details: [`examples/ffi/rust/`](examples/ffi/rust).

**`gg bindgen`** turns a C header (`#define` integers, `enum` constants, `struct`s, prototypes) into `extern` declarations:

```bash
gg bindgen mylib.h -o mylib_bindings.gg
gg bindgen mylib.h --header-name mylib.h
```

---

## Project Structure

```
greengold/
  lexer.py         Tokens, INDENT/DEDENT, indentation repair
  parser.py        Recursive descent parser
  ast_nodes.py     AST nodes, unparser, AST dump
  typecheck.py     Types, symbols, move analysis, prelude loading
  borrow.py        Stored `read` / `lend` reference checks
  matchcheck.py    Enum constructors, exhaustive `match`, `?`
  generics.py      Generic registry, inference, monomorphization
  comptime.py      `comptime fn` interpreter
  typeinfo.py      Type predicates, mangling, metadata records
  codegen_llvm.py  LLVM IR generator
  llvm_driver.py   Optimization, object code, linking
  recur_inline.py  Release-mode recursion inlining on IR text
  diagnostics.py   Diagnostics: text and JSON rendering, fix-its
  codes.py         GGxxxx error code catalog
  cli.py, tools.py Command line, gg.toml, test runner, fmt, doc, build cache
  lsp.py           Language server
  bindgen.py       C header -> extern declarations
  core/core.gg     Core library: Optional, Result, string (written in Greengold)
  std/*.gg         Standard library (math, string, collections, fs, process, thread, ...)
examples/          Example programs (run by the test suite)
tests/             pytest suite (`python -m pytest -q`)
selfhost/          Self-hosted compiler, frozen at tag `selfhost-freeze`
docs/
  SPEC.md                Language reference (normative)
  GRAMMAR.md             Grammar
  DESIGN.md              Design decisions and rationale
  FEATURES_DEFER_REF.md  Guide: features, defer, references, ownership
  ERROR_CODES.md         Diagnostic codes
Learn/             Step-by-step tutorial
```

## Tests

```bash
python -m pytest -q
```

End-to-end tests need `gcc` or `clang` on `PATH` for linking. The frozen self-host parity tests run only with `GG_SELFHOST=1`. Every `gg` code block in `README.md`, `docs/`, and `Learn/` that has a `fn main` is type-checked by `tests/test_doc_examples.py`.

## Support

Greengold is a one-person project and stays free and open source. If you want to help pay for development time, Linux and macOS testing, and hosting, you can support it on [Patreon](https://www.patreon.com/greengoldlang). Bug reports, feedback and code contributions help just as much, see [CONTRIBUTING.md](CONTRIBUTING.md). Come chat on [Discord](https://discord.gg/sp65habzne).

## License

MIT, see [LICENSE](LICENSE).
