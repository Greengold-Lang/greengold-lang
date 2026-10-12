# The Greengold Programming Language: A Complete Learning Guide

Welcome! This guide is the official tutorial series for **Greengold (.gg)**, a modern systems programming language. It takes you from zero to writing robust, safe, high-performance software.

The biggest dilemma in designing a systems language is this: **be as fast and close to the hardware as C, or offer the memory and type safety of modern languages?** Greengold combines the two. It avoids Rust's complex `'a` lifetime syntax and offers zero-cost abstractions with Go-like simplicity and C++-like speed.

---

## 🌟 Greengold's Core Philosophy

Greengold is built on the following design principles:

1. **Easy Variables, Visible Immutability:**
   Variables are mutable by default; you do not need an extra word to write a counter. The compiler treats a variable that is never changed as `fixed` on its own, and the editor shows this as a hint. When you want to guarantee that a value never changes, you write `fixed`.

2. **Explicit Intent (Modes):**
   Side effects are not hidden in function calls. Whether a value is only read (`read`), updated in place (`lend`), or has its ownership handed over (`consume`) is written on the signature. The call site stays `f(x)`.

3. **Memory Safety Without Lifetime Syntax:**
   References (`lend` / `consume`) cannot be stored in local variables or struct fields; they live only within a function call frame. Dangling pointers and use-after-free errors become impossible.

4. **Zero-Cost Abstractions:**
   Generic types, structural features, `defer`, and view types (`ref T`) are resolved at compile time. There is no virtual method table (vtable) overhead and no garbage collector pause at run time.

5. **LLVM Backend:**
   Greengold compiles through LLVM IR to highly optimized machine code (`-O3`).

---

## 📚 Curriculum and Contents

This series has 11 chapters that build on each other. Following them in order is recommended:

| Chapter | Topic | Description |
|---|---|---|
| [**01. Basics and Types**](01_Basics_and_Types.md) | Variables, numeric types, expressions | `fn main()`, variables (`=`), `fixed`, primitive types, numbers, and language rules |
| [**02. Control Flow and Loops**](02_Control_Flow.md) | Conditions, range loops, iterators | `if/elif/else`, inline `if-then-else`, `while`, exclusive/inclusive ranges, indexed loops, `break`/`continue` |
| [**03. Functions, Methods, and Lambdas**](03_Functions_Methods_and_Lambdas.md) | Function signatures, `impl`, lambdas | Functions, `impl` method blocks, static methods, function pointers `fn(...) -> T`, anonymous lambdas `=>` |
| [**04. Ownership, Modes, and Memory**](04_Ownership_Modes_and_Memory.md) | `read`, `lend`, `consume`, `defer` | Greengold's memory backbone: parameter modes, Copy vs Move types, automatic `drop`, `defer` cleanup |
| [**05. Data Structures and Tuples**](05_Data_Structures_and_Tuples.md) | Struct, enum, tuple, destructuring | `struct`, algebraic `enum`, tuples `(A, B)`, destructuring assignment `a, b = t`, fixed arrays `[N]T`, slices `[]T` |
| [**06. Pattern Matching**](06_Pattern_Matching.md) | `match`, `if let`, `while let` | `match` statements and expressions, algebraic enum matching, scalar ranges, wildcard `_`, `if let` and `while let` |
| [**07. Generics, Features, and Operator Overloading**](07_Generics_Features_and_Operator_Overloading.md) | Monomorphization, structural features, overloading | Generic functions/types, Go-style structural feature bounds `[T: Num + Ord]`, operator overloading (`add`, `neg`, `eq`...) |
| [**08. Error Handling and the Core Library**](08_Error_Handling_and_Prelude.md) | `Optional`, `Result`, the `?` operator | Null safety, `Optional[T]`, `Result[T, E]`, the `?` propagation operator, error conversion (`from`), `panic` |
| [**09. Standard Library and Concurrency**](09_Standard_Library_and_Concurrency.md) | `std.*` modules, threads, collections | `std.fs`, `std.string`, `std.math`, `std.time`, `std.thread` (threads, mutexes, channels), heap collections (`List`, `Box`) |
| [**10. FFI, Raw Pointers, and Systems Programming**](10_FFI_Unsafe_and_Systems_Programming.md) | C interop, `*T`, `unsafe:` blocks | Linking C libraries (`extern`), raw pointers `*T` and `*mut T`, the `unsafe:` safety boundary, memory conversions |
| [**11. Project Management and Developer Tools**](11_Project_Management_and_Tooling.md) | `gg.toml`, packages, format and test | `gg new`, `gg run`, `gg build`, `gg fmt`, `gg test`, `gg doc`, the VS Code extension and LSP |

---

## 🛠️ Installation and Your First Program

### 1. Install Greengold

You do not need Python. The installer puts the single `gg` command on your `PATH` (see the [README](../README.md#install) for options).

**Windows** (PowerShell):

```powershell
irm https://raw.githubusercontent.com/Greengold-Lang/greengold-lang/main/installer/install.ps1 | iex
```

**Linux and macOS:**

```bash
curl -fsSL https://raw.githubusercontent.com/Greengold-Lang/greengold-lang/main/installer/install.sh | sh
```

Open a new terminal and check it:

```bash
gg --version
gg --help
```

Later, `gg update` installs the newest version. If you work from a source checkout instead, `pip install -e .` gives the same `gg` command, and `python -m greengold` works as well.

### 2. First Greengold Program: "Hello, Greengold!"

Create a new file, for example `hello.gg`:

```gg
# hello.gg - My first Greengold program
fn main():
    print("Hello, Greengold World!")
```

### 3. Running and Building

To run your program directly:

```powershell
gg run hello.gg
```

To create an optimized native executable:

```powershell
gg build --release hello.gg -o hello.exe
.\hello.exe
```

To inspect the LLVM IR output:

```powershell
gg emit-ll hello.gg
```

---

When you are ready, start the journey into the heart of the language with [Chapter 01: Basics and Types](01_Basics_and_Types.md)!
