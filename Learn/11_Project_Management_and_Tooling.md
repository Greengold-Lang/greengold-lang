# Chapter 11: Project Management and Developer Tools

A programming language's developer experience (DevEx) is as important as its syntax. Greengold offers every tool a modern developer needs in a single **`gg`** command-line interface (CLI), with no need for external package managers or third-party linter/formatter installations.

---

## 1. Starting a New Project (`gg new`)

Creating a new Greengold project takes a single command:

```powershell
gg new my_project
cd my_project
```

This command sets up the standard project hierarchy automatically:

```text
my_project/
├── gg.toml         # Project and dependency manifest
└── src/
    └── main.gg     # Main entry point and sample code
```

---

## 2. The Package Manifest: `gg.toml`

`gg.toml` manages your project's identity, its entry file, and its other local module dependencies:

```toml
[package]
name = "my_project"
version = "0.1.0"
main = "src/main.gg"

[dependencies]
# Local module and library dependencies:
# math_utils = { path = "../shared/math_utils" }
```

Once a dependency is added, you can write `import math_utils.matrix` in a file of your project. This binds the name `matrix` in that file. From the outside, all names that are not under a `private` line are visible: `matrix.mul(a, b)`. Names inside the same file stay unqualified. `import math_utils.matrix as m` renames the binding. `import math_utils.matrix { mul }` brings in the chosen name without qualification. An import is not re-exported; each file writes its own `import` lines. `fn main` exists only in the root file you compile. The build is still a single program; each file does not produce a separate object file.

---

## 3. Running and Building Commands

### 3.1 Quick Run (`gg run`)
For a fast code loop during development, it compiles the program directly and runs it:

```powershell
# Quick run in debug mode:
gg run

# Run at maximum speed with LLVM -O3 optimizations:
gg run --release
```

### 3.2 Building a Binary (`gg build`)
Produces a standalone, distribution-ready native executable:

```powershell
# Build a debug binary:
gg build -o my_app.exe

# An optimized, minimum-size release binary:
gg build --release -o my_app_release.exe
```

### 3.3 Smart Build Cache
Greengold has a smart incremental build cache (`.gg-cache/`) that computes the SHA-256 content hash of the source code. When your code has not changed, the build answers `Up to date (cached)` at once and avoids unnecessary rebuilds.

---

## 4. Fixing Errors Automatically (`gg fix`)

If the compiler knows the fix for an error, it writes it next to the error and verifies it by trying it on a copy of the file (`fix (verified)`). `gg fix` applies the verified fixes to the file and repeats until no fixes remain:

```powershell
gg fix              # every .gg file in the current folder
gg fix src/main.gg  # a single file
gg fix --dry-run    # only prints what would be done
gg fix --likely     # also applies guess-based fixes that compile
```

There are two kinds of fixes:

* **`safe`:** the one sensible repair. Spellings that come from other languages such as `&&`, `||`, `!x`, `x++`, `;`, `let x = 5`, `def`; a `:` forgotten at the end of a line; a missing `import std.math` for `sqrt`; `Valid(3)` instead of `Some(3)`; `xs.push(1)` instead of `xs.append(1)`; an `impl P:` block instead of `fn P.get`.
* **`likely`:** a guess that compiles. A misspelled name (`cout` → `cnt`), an `i32(...)` conversion, missing arms in a `match`, missing fields in a struct literal.

A syntax error does not stop compilation: the faulty line is skipped and the rest of the file is still checked. A single `gg check` run shows all the errors; only the errors that stem from the skipped line are hidden.

---

## 5. The Automatic Code Formatter (`gg fmt`)

An end to code formatting debates! `gg fmt` brings every file to a single style: four spaces per block, `else`/`elif` aligned with their own `if` line, and trailing whitespace removed. Formatting the same file a second time changes nothing.

```powershell
# Format a specific file or the whole src directory:
gg fmt src/

# Only check the formatting (for CI/CD processes):
gg fmt --check src/
```

The formatter cleans up unnecessary whitespace without changing the meaning of your code, and it guarantees the formatting.

---

## 6. The Automatic Test Runner (`gg test`)

You do not need to install an external test library. In a file, every function written in the `fn test_*():` format is automatically treated as a unit test:

```gg
# src/math.gg
fn add(a: i32, b: i32) -> i32:
    return a + b

# Unit test functions:
fn test_addition():
    if add(2, 3) != 5:
        panic("Addition test failed!")

fn test_negative_numbers():
    if add(-5, 5) != 0:
        panic("Negative number test failed!")
```

A `test` block can also be written right below the function. The block belongs to the function above it. The body is normal code. If a `require` is false, that test fails. `fn main` does not call this block.

```gg
fn add(a: i32, b: i32) -> i32:
    return a + b

test:
    require add(2, 3) == 5

test negatives:
    require add(-1, 1) == 0
```

To run the tests:

```powershell
gg test src/

# Write the same result as JSON:
gg test src/ --json
```

Output:
```text
test_addition ... ok
test_negative_numbers ... ok
Tests passed: 2, failed: 0
```

If a test function produces a `panic`, the test is marked FAILED and the error is reported.

---

## 7. The Automatic Documentation Generator (`gg doc`)

Comment lines written with `#` right above function and struct definitions in your code are turned into Markdown API documentation automatically:

```gg
# Lets the calculator add two numbers.
# Parameters:
#   a: The first addend
#   b: The second addend
fn add(a: i32, b: i32) -> i32:
    return a + b
```

To build the documentation:

```powershell
# Print to the screen:
gg doc src/

# Save to a Markdown file:
gg doc src/ -o API_DOCS.md
```

---

## 8. Compiler Inspection Commands

For advanced developers and system architects, Greengold can export the compilation stages:

* **`gg emit-ll file.gg`:** Dumps the LLVM IR intermediate representation as text.
* **`gg emit-bc file.gg`:** Produces an LLVM Bitcode (.bc) file.
* **`gg ast file.gg`:** Inspects the syntax tree (AST) hierarchically.
* **`gg attrs file.gg`:** Lists every `@attribute` use (functions, structs, fields) as JSON, for code generators. See [Chapter 03, section 5](03_Functions_Methods_and_Lambdas.md).

---

## 9. VS Code Integration

The official Greengold VS Code extension (`greengold-vscode`) offers a full IDE experience with the built-in Language Server Protocol (LSP):

* **Real-Time Error Detection:** Instant syntax and ownership checks as you type (red underlines).
* **Go to Definition (`F12` / `Ctrl+Click`):** Jump instantly to function, struct, enum, and `import` targets.
* **Hover Tooltips:** View the documentation of types, methods, and Greengold keywords.
* **Smart Code Completion (IntelliSense):** When you type a dot (`.`), object methods and fields are listed automatically.
* **Automatic Code Formatting (`Shift+Alt+F`):** Instant formatting to `gg fmt` standards.
* **Quick Fixes (💡 / `Ctrl+.`):** Every fix from the compiler appears in the lightbulb menu. When you save the file, `safe` fixes are applied on their own (the same as `gg fix`).
* **Integrated Buttons:** One-click running with the Run `$(play)`, Release `$(rocket)`, and Build `$(tools)` buttons in the top-right corner of the editor.

---

## 🎓 Congratulations: You Are Now a Greengold Developer!

Over 11 chapters, you learned:
* The philosophy of immutability and the strong primitive types,
* Rich control flow and custom iterators,
* Methods, `impl` blocks, and zero-cost lambdas,
* The three parameter modes (`read`, `lend`, `consume`) and memory safety without `'a` syntax,
* Structs, enums, tuples, and destructuring assignments,
* Pattern matching, and the `if let` and `while let` constructs,
* Structural features and operator overloading,
* The `Optional`, `Result`, and `?` error propagation architecture,
* The standard library modules and concurrency,
* Systems programming at the C/FFI level with `extern` and `unsafe:`,
* And the modern `gg` toolchain.

We wish you success with the fast, safe, and elegant systems software you will write with Greengold! 🚀
