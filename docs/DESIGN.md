# Greengold Design Decisions and Rationale

This document explains the rationale behind the key architectural and semantic design decisions in versions v1, v2, and v3 of the Greengold programming language.

> The rules themselves live in [`SPEC.md`](SPEC.md). This file explains *why*; when the two disagree, the spec wins.

---

### 1. Variables Can Change; The Compiler Tells You Which Ones Do Not
A newcomer expects `x = 0` followed by `x += 1` to work, so it does: there is no second keyword to learn before a counter compiles. Unexpected mutation is still visible. The compiler finds every variable that nothing changes and treats it as `fixed`; the editor shows that word in front of it as an inlay hint, so the reader sees which values stay put without the writer typing anything. When a value must never change, write `fixed x = ...`: then assigning, lending, or calling a changing method on it is an error. The same idea applies to `for x in xs:` — changing `x` in the body makes it lend each element, and the hint shows `lend`.

### 2. Parameter Modes Are Written Once, On The Signature
`read` is a shared borrow, `lend` is the exclusive mutable borrow, and `consume` moves. The mode is written on the parameter (`fn finish(c: consume Player)`). The call stays `finish(c)`. Repeating the mode at every call would say the same thing twice and would drift from Python, which models already write fluently. What the call does is recoverable from the signature: `gg check --json` puts the callee and the parameter on the diagnostic. There is no `own` keyword.

For a heap-owning parameter the mode may be left out: the compiler infers `read`, `lend`, or `consume` from what the body does, and re-checks callers with that mode. A diagnostic at a call site names the inferred mode and why. Copyable parameters are not inferred: whether a struct is copied or shared would otherwise depend on the body.

### 3. Stored references, unnamed lifetimes
Dangling pointers and use-after-free bugs are among the hardest problems in systems programming; solving them at compile-time typically requires complex lifetime systems like Rust's. Greengold does not add named lifetimes. `read T` and `lend T` are non-owning pointers (`T*`): they are not dropped. They may be parameters, local variables (`r: read T = place`, `r = read place`), or struct fields (`who: read Player tied to self`). A stored reference is tied to the root place it was borrowed from. Moving that root, reassigning it, or taking `lend` of it while the reference is still used is a compile error. `read` still allows other reads; `lend` is exclusive for as long as the holder is used later. A reference into an inner scope cannot be stored in an outer variable or returned. Slices (`[]T`) remain parameter-only. Views carried by value (`str`, and values holding one) follow the same rule: a view made from a heap-owning variable is tied to that variable, without any annotation.

### 4. Slices (`[]T`) Allowed Only as Parameters
Slices are dynamically sized views over fixed-size arrays or memory blocks (fat pointers: `ptr + len`). Allowing slices in local variables could lead to invalid memory access if the underlying array goes out of scope. Accepting slices only as function parameters allows zero-copy views into arrays while preserving lifetime safety.

### 5. Python-Style Bitwise Precedence and Parenthesization
In C, bitwise operators (`&`, `^`, `|`) historically have lower precedence than relational operators (`==`, `!=`, `<`, `>`), which often causes subtle logic bugs like `a & mask == expected`. Greengold adopts Python's operator precedence, which aligns more intuitively with mathematics and logic (`==` binds tighter than bitwise operations). At the transpiler level, all binary expressions are fully parenthesized to prevent C precedence rules from interfering.

### 6. Debug and Release Modes with Runtime Checks
During development, catching memory and indexing errors immediately is essential, while in production, maximum performance is expected. In debug mode (`-O0 -g`), array/slice/string bounds checks, division by zero, division overflow, and invalid shifts are caught at runtime and reported with exit code 101 and uniform error messages on stderr. In release mode (`--release`, LLVM `-O3`), array/slice/string **bounds checks and division checks remain enabled**: memory safety is not an optional optimization. Disabling bounds checks is only possible via an explicit `--unchecked` opt-out (out-of-bounds access in that mode is undefined behavior). Integer `+`, `-`, and `*` trap on overflow unless the operation is `wrapping_*` or sits in a `wrapping:` block.

---

## v2 Decisions

### 7. Postponed Checking of Generics at Instantiation Time
A generic body is typechecked afresh for each distinct set of concrete type arguments (like C++ templates); no feature bounds are required on `T`. Thus, whether an operation like `a > b` is valid is determined when instantiated with a concrete type like `T = Player`, producing natural error messages without introducing feature system complexity to v2. The tradeoff is that uninstantiated generics are not checked, and errors are pinned to the call site with a note such as "instantiated with T = Player, call: ...".

### 8. `match` Modes Match Parameter Modes
`match s:` reads, `match lend s:` mutates in place, and `match consume s:` moves the scrutinee. The same three words as parameters. In `consume` mode the scrutinee is moved before the arms run, so each arm is checked on its own. There is no `own` mode.

### 9. Bare Identifier in Pattern = Variant
To someone reading `Circle(r):`, `Circle` is a variant and `r` is a new variable binding; unused fields are written with `_`. Treating bare identifiers as variable bindings (as in Rust) would silently turn typos into catch-all arms; therefore, an unrecognized bare identifier is a compile error. In expressions (`Shape.Circle(1.0)`), qualification is required because variant names and variable names cannot otherwise be distinguished there.

### 10. `?` Only Allowed as Full Expression
Because `?` is a hidden early `return`, placing it inside nested sub-expressions would make evaluation order and move analysis unreadable (e.g., does `h()` get called in `g(f()?, h())`?). Restricting `?` to `x = f()?`, `x = f()?`, `return f()?`, and statement `f()?` keeps code generation simple (temporary variable + tag check + `return`) and ensures move analysis treats early returns as normal `return`s.

### 11. Prelude (Optional/Result) Written in Greengold
`Optional` and `Result` are not compiler-internal magic types; they are standard generic enums and methods defined in `greengold/core/core.gg`. This continuously exercises generics and enums against real workloads (if the prelude breaks, every program breaks) and ensures that adding new types in future versions follows the same path. Beyond short constructors (`Some`, `None`, `Ok`, `Err`), reserved names, and `?`, the compiler contains no special-case code for these types.

### 12. If/Else-If Chains Instead of `switch` for `match`
(Written for the removed C99 backend; the LLVM backend lowers `match` the same way.) In C, `break` inside `switch` breaks out of the switch, whereas in Greengold, `break`/`continue` inside `match` must affect the enclosing loop. An if/else-if chain provides this behavior naturally; the scrutinee is evaluated once into a temporary variable, and because exhaustiveness is verified at compile-time, the final arm becomes an unconditional `else`. C compilers already optimize such chains effectively.

### 13. Naming (Greengold / .gg)
The language's former codename was "Re" with file extension `.re`. Rationale: the `.re` file extension conflicted with ReasonML; the `re` console command and name conflicted with Python's standard library module (`import re`). For these reasons, the language was named **Greengold**, the file extension **.gg**, the Python package **greengold**, and the CLI tool **gg**.

### 14. Copy vs. Move Rules (Per Type)
Copy types: all numeric types, `bool`, `str` (a view), raw pointers, fixed-size arrays containing only Copy types, and structs and enums that hold none of the move types. Move types: `Box`, `List`, `string` (an owned, growing buffer), the OS handles of `std.thread`, and any struct or enum that holds one of them; these move on assignment or `consume` and cannot be used after the move. Slices are never copied or moved; they can only be parameters. Passing a Copy type with `consume` is an error (unnecessary). Heap-owning types are strictly Move (copying them would cause double-free) and are automatically `drop`ped at end of scope (see item 16). Structs and enums without heap fields continue to be passed by value (copied).

### 15. `extern` Safety Boundary
External C code cannot be verified by the compiler; therefore, the `extern` surface is deliberately restricted: parameters can only be numeric/`bool`, `string` (as a temporary NUL-terminated pointer), `read`/`lend` structs, or raw pointers; `consume`, slices, arrays, and heap types cannot be parameters, and returning `string`/struct is prohibited (returns: numeric, `bool`, pointer, `void`). Passing/returning structs by value depends on platform ABI (SysV, Windows x64) and is deliberately unsupported; they must be passed via pointer. The correctness of an `extern` call (e.g. not mutating a struct passed as `lend`) relies on programmer discipline.

**Raw pointer and `unsafe` boundary (FFI).** `*T` (read-only), `*mut T`, and `*void` exist solely to interface with C. In safe code, pointer values can be passed, stored, and compared with `==`/`null` (they are Copy types with no ownership/drop); but all of the following require an `unsafe:` block: reading/writing `p[i]`, `addr`/`addr_mut`, `ptr_cast`, `ptr_offset`, `ptr_to_int`/`int_to_ptr`, `cstr_to_string`/`string_to_cstr`, and calling pointer-accepting/returning or variadic `extern` functions. Inside `unsafe:`, the compiler DOES NOT GUARANTEE: pointer validity/alignment/lifetime, bounds checking on `p[i]` (there is none), absence of data races, that C memory modified via `*mut` adheres to Greengold's `read`/`lend` rules, or that the view returned by `cstr_to_string` is not used after C memory is freed. Borrow/move analysis does not track pointers (`addr(x)` does not borrow; if `x` is reassigned or goes out of scope, the pointer dangles). Leak/double-free responsibility lies on the C (or Rust) side: memory allocated via C `malloc` is not automatically `drop`ped by Greengold; the appropriate C `free` function must be called. A pointer target type can be numeric, `bool`, struct (non-heap-owning), `void`, or another pointer; it cannot be `string`, array, slice, enum, or `Box`/`List`. `extern struct` only permits C-compatible fields (numeric, `bool`, pointer, nested `extern struct`, or arrays thereof).

---

## v3 Decisions: Heap and Ownership

### 16. Box[T] and List[T]: Built-In Owning Types
Box[T] (single value, accessed via `b.value`, read/written as an lvalue) and List[T] (dynamic array: `push`, `pop`, `clear`, `.len`, `v[i]`) are built into the compiler; their names are reserved. Owning types (any struct/enum containing `Box`/`List`) **are not copied, only moved**: storing a place in a new owner moves it (`a = b`, `S{ f: v }`, `Cons(1, rest)`), and passing it to a `consume` parameter moves it. `consume` is written only on parameters, never at the use site. At end of scope or early return via `return`/`break`/`continue`/`?`, owners are automatically `drop`ped. The compiler tracks a runtime liveness flag (`_gg_live_x`) for each owner variable, ensuring conditional moves are safe.

Constraints (deliberate): no partial moves (moving `p.field` alone is an error), no arrays of heap elements, an element of a heap list (`v[i]` in `List[List[T]]` or `List[string]`) is a place that can be read and changed but not moved out (use `v[i].clone()` or `pop`), and prelude `value_or_panic`/`value_or` error on heap payloads (use `match consume`). `x.clone()` deep-copies any value that holds no `lend` reference. An owning *temporary* lent to a call (`f(Box[i32](1))`, `string.from("x").len()`) is freed right after the call. When the call's result may point into that temporary (a `str`, a slice, a pointer, a `ref`, or a struct holding one, as in `make().as_str()`), the temporary is kept alive to the end of the enclosing block (or the function, when the statement stores such a view). A fresh value used only as the base of a field, element, `.len`, or built-in method (`make().text.as_str()`, `nums()[0]`) is freed the same way. The `GG_LEAKCHECK=1` environment variable reports unfreed blocks to stderr on exit (used in test suites).

### 17. `-> ref T` and `-> lend T`: pointers derived from one parameter
A function can return a non-owning pointer with `-> ref T` (shared) or `-> lend T` (exclusive). The ABI is `T*`; the result is not dropped. Every `return` must be a place derived from the same `read` or `lend` parameter (`p`, `p.field`, `p.items.get(i)`, or a reference local tied to that parameter). The parameter does not have to be the first one. When more than one parameter could be the origin, write `-> ref T tied to name`. A by-value or `consume` parameter cannot be the origin: its slot dies when the function returns. Heap-owning parameters are already `read` by default. At the caller, `x = f(s)` stores that pointer; `x: T = f(s)` still asks for an owned value and rejects a heap view. The pointer can be read, matched, indexed, and passed as `read` (or mutated, when it is `lend`). It cannot be `consume`d. `List.get(i)` is a built-in, bounds-checked `read` of the element.

### 18. If and Match as Expressions
Can be used in any expression context: variable initialization, assignment, return, argument: `x = if c then a elif d then b else e` (`else` required, no colons) and `y = match s:` followed by indented `Arm(a, b) => value` lines. All arms must evaluate to the exact same type; exhaustiveness, `match consume` / `match lend`, move analysis, and automatic drop share the same engine as statement forms (internally represented as If/Match statements where each arm body is a single `Yield`). Heap-owning results (a moved value, or a fresh value) are supported. Limitations: a `match` expression must be the last element on its line (no trailing operators); each arm must be a single expression (use statement `match` for multi-line bodies); `return`/`break` are not permitted inside arms.

### 19. Defer
`defer call` (or assignment) executes in reverse order (LIFO) at scope exit, including early returns via `return`/`break`/`continue` (similar to Zig: arguments are evaluated at scope exit). Scopes are block-based; `defer` shares the cleanup stack with automatic drops of heap owners (deferred statements execute before owning variables are dropped). `defer f()?` is disallowed.

### 20. Features (Structural, Static Dispatch, Default Bodies)
Declared as `feature Shape:` with signatures (`fn area(self: Self) -> f64`) and optional default method bodies (`fn double(self: Self) -> f64: return 2.0 * self.area()`; `Self` represents the implementing type). Features use structural typing (like Go): if a struct implements all methods of a feature that do not have a default body, it automatically satisfies the feature and gains the feature's default methods (missing even a single non-default method invalidates feature conformance). Structs can override default methods in `impl Type:`. Features are used as *bounds*: `fn sum[T: Shape](a: T, b: T)`, `struct Box[T: Num + Ord]`. Bounds are checked at instantiation time and missing/incompatible methods are reported at the call site; the body is compiled via monomorphization (zero runtime overhead). Built-in bounds: `Num`, `Int`, `Float`, `Ord`, `Eq`. Deliberate limitations: no dynamic dispatch (feature objects); generic type method signatures are checked by parameter count and mode only.

## v4 design notes

- **Operator overloading**: binary/unary operators map to methods (`add`, `sub`, `mul`, `div`, `rem`, `neg`, `eq`/`lt`... only when such a method exists); the typechecker annotates `e.overload` and both backends emit a method call.
- **Function pointers**: type `fn(A)->R`; capture-free lambdas are lifted to hidden top-level functions. `lend`/`read` parameters cannot be used as function values.
- **Iterators**: `for x in it` desugars into a `next()`-driven loop when `it`'s type has `next(self: lend T) -> Optional[U]`.
- **Static methods / `?` conversion**: a method without `self` is called as `Type.name(..)`; `?` applies `Target.from(e)` when error types differ.
- **Modules.** Each file is a module in one compilation. Imports are file-local. A file starts public: a beginner's second file works without extra words. A `private` line hides the declarations below it; `public` shows them again. Other files use `module.name`. There is no per-file object file.
- **Stdlib** lives in `greengold/std/*.gg` (imported with `import std.name`, called as `math.sqrt`); **concurrency** (`std.thread`) is a thin pthread FFI layer, not a type-system feature (no Send/Sync).
- **Tooling**: `gg.toml` + path dependencies, `gg new/fmt/test/doc`, content-hash build cache.
- **Self-hosting**: `selfhost/lexer.gg` is a complete lexer in Greengold, verified token-for-token against `greengold/lexer.py` on the example/stdlib corpus (it also lexes its own source). The parser/typechecker/codegen are still Python.
- **C99 backend**: removed. LLVM is the only code generator.

