# Greengold Language Guide: Features, Defer, Ref, and Memory Mechanisms

This document comprehensively explains **Features (`feature`)**, **Deferred Execution (`defer`)**, **Unowned Views (`-> ref T`)**, and the directly related ownership, memory safety, and modern features in the **Greengold** programming language.

---

## Table of Contents
1. [Greengold Philosophy and Design Principles](#1-greengold-philosophy-and-design-principles)
2. [Features (`feature`) and Generic Bounds](#2-features-feature-and-generic-bounds)
   - [2.1 What is a Feature and How is it Defined?](#21-what-is-a-feature-and-how-is-it-defined)
   - [2.2 Structural Conformance (No Explicit `impl`)](#22-structural-conformance-no-explicit-impl)
   - [2.3 Generic Bounds (Feature Bounds) and Multiple Bounds (`+`)](#23-generic-bounds-feature-bounds-and-multiple-bounds-)
   - [2.4 Built-in Features (`Num`, `Int`, `Float`, `Ord`, `Eq`)](#24-built-in-features-num-int-float-ord-eq)
   - [2.5 Static Dispatch (Zero-Cost Monomorphization)](#25-static-dispatch-zero-cost-monomorphization)
3. [Deferred Execution (`defer`)](#3-deferred-execution-defer)
   - [3.1 What is Defer and Why is it Used?](#31-what-is-defer-and-why-is-it-used)
   - [3.2 Execution Order (LIFO - Reverse Order)](#32-execution-order-lifo---reverse-order)
   - [3.3 Early Exits (`return`, `break`, `continue`)](#33-early-exits-return-break-continue)
   - [3.4 Interaction with Automatic `drop`](#34-interaction-with-automatic-drop)
   - [3.5 Rules and Constraints](#35-rules-and-constraints)
4. [Stored references and `-> ref` / `-> lend`](#4-stored-references-and---ref----lend)
   - [4.1 What a reference is](#41-what-a-reference-is)
   - [4.2 One-parameter origin](#42-one-parameter-origin)
   - [4.3 Why no Rust-style lifetimes (`'a`)?](#43-why-no-rust-style-lifetimes-a)
   - [4.4 What a stored reference may do](#44-what-a-stored-reference-may-do)
   - [4.5 Built-in Example: `List[T].get(i)`](#45-built-in-example-listtgeti)
5. [Related System Mechanisms ("vs.")](#5-related-system-mechanisms-vs)
   - [5.1 Parameter Modes: `read`, `lend`, and `consume`](#51-parameter-modes-read-lend-and-consume)
   - [5.2 Heap Memory (`Box[T]`, `List[T]`) and Automatic `drop`](#52-heap-memory-boxt-listt-and-automatic-drop)
   - [5.3 `if` and `match` as Expressions](#53-if-and-match-as-expressions)
   - [5.4 Error Handling: `?` Operator, `Optional`, and `Result`](#54-error-handling--operator-optional-and-result)
6. [Comparative Summary Table](#6-comparative-summary-table)

---

## 1. Greengold Philosophy and Design Principles

Greengold is a statically typed, indentation-sensitive systems programming language that compiles to LLVM IR and machine code. The normative rules are in [`SPEC.md`](SPEC.md). Its core goals:

* **Zero-Cost Abstractions:** Abstractions (generics, features, `defer`, views) are resolved at compile time into clean, optimized native code.
* **Memory Safety without Hidden Complexity:** Prevents pointer and deallocation errors (dangling pointers, double free, use-after-free) without introducing the cognitive burden of Rust-style explicit lifetime annotations (`'a`).
* **Explicit Intent, Written Once:** Mutation borrowing (`lend`), and ownership transfer (`consume`) are stated in the signature. The call site stays `f(x)`.

---

## 2. Features (`feature`) and Generic Bounds

### 2.1 What is a Feature and How is it Defined?

A **feature** is a collection of method signatures and optional default method bodies defining a set of behaviors or capabilities. It is analogous to interfaces/features in modern languages, operating statically in Greengold.

It is declared at the top level with `feature Name:`. In method signatures, the implementing type is represented by the `Self` keyword. Methods may either be bodiless signatures or provide a **default body**:

```gg
feature Shape:
    fn area(self: Self) -> f64
    fn scale(self: lend Self, k: f64)
    # Default method body:
    fn double_area(self: Self) -> f64:
        return 2.0 * self.area()
```

Here:
* `self: Self`: Indicates the method takes the object read-only (by value copy or view).
* `self: lend Self`: Indicates the method borrows the object mutably.
* `fn double_area(...)`: Provides a default implementation. Implementing structs do not need to implement it.

### 2.2 Structural Conformance (No Explicit `impl`) and Default Bodies

Greengold adopts **structural typing (Go-style)**. A type does not need an explicit declaration like `impl Shape for Circle` to satisfy a feature.

**Automatic Feature Conformance Rule:**
* If a `struct` or `enum` implements all methods in a feature that **do not have a default body** with matching signatures, it is **automatically considered to have that feature**.
* Any default methods provided by the feature are automatically synthesized and made available on the struct.
* If a struct explicitly implements a method with a default body, the struct's implementation overrides the default.
* If **even a single method without a default body is missing**, the feature is considered absent, and default methods are not attached.

```gg
struct Circle:
    r: f64

impl Circle:
    # Satisfies the required `area` method of Shape:
    fn area(self: Circle) -> f64:
        return 3.14159 * self.r * self.r

    # Satisfies the required `scale` method of Shape:
    fn scale(self: lend Circle, k: f64):
        self.r *= k

    # `double_area` has a default body in Shape, so Circle does NOT need to implement it!
```

Because `Circle` matches all required methods of `Shape`, it automatically has the `Shape` feature and inherits `double_area`:

```gg
fn main():
    c = Circle{ r: 2.0 }
    print(c.double_area())  # Works automatically via feature default body!
```

### 2.3 Generic Bounds (Feature Bounds) and Multiple Bounds (`+`)

In Greengold, features are used **exclusively as bounds on generic type parameters** (they cannot be used as standalone dynamic types or feature objects).

#### Usage in Functions:
```gg
fn print_area[T: Shape](s: T):
    print("Area:", s.area())

fn enlarge[T: Shape](s: consume T):
    s.scale(2.0)
```

#### Usage in Structs and Enums:
```gg
struct Container[T: Shape]:
    item: T
```

#### Multiple Bounds (`+` Operator):
If a type parameter must satisfy multiple features, combine them with `+`:
```gg
fn process[T: Num + Ord](a: T, b: T) -> T:
    if a > b:
        return a
    return b
```

> **Note:** Methods of generic types (`impl Container[T]: fn do_something(...)`) do not repeat the bounds; the bound is already declared in the type's primary definition (`struct Container[T: Shape]:`).

### 2.4 Built-in Features (`Num`, `Int`, `Float`, `Ord`, `Eq`)

Greengold provides 5 built-in features for primitive types:

| Feature | Covered Types | Description |
|---|---|---|
| `Num` | `i8`..`i64`, `isize`, `u8`..`u64`, `usize`, `f32`, `f64` | All numeric types. |
| `Int` | `i8`..`i64`, `isize`, `u8`..`u64`, `usize` | Signed and unsigned integers only. |
| `Float`| `f32`, `f64` | Floating-point numbers only. |
| `Ord` | Numeric types | Types supporting ordering comparisons (`<`, `<=`, `>`, `>=`). |
| `Eq` | Numeric types, `bool`, `string` | Types supporting equality comparisons (`==`, `!=`). |

Example:
```gg
fn max[T: Ord](a: T, b: T) -> T:
    if a > b:
        return a
    return b

fn main():
    print(max(10, 20))       # Valid: i32 satisfies Ord
    # print(max(true, false)) # COMPILE ERROR: `bool` does not satisfy Ord!
```

### 2.5 Static Dispatch (Zero-Cost Monomorphization)

There are **no feature objects (no dynamic vtable dispatch)** in Greengold.
All feature bounds are resolved at compile time:
1. When calling `max(10, 20)`, code is generated specifically for `T = i32`.
2. There is no indirect function pointer overhead or lookup table penalty.
3. The backend compiler can inline these functions directly; runtime overhead is **strictly zero**.

---

## 3. Deferred Execution (`defer`)

### 3.1 What is Defer and Why is it Used?

`defer` postpones the execution of a function call or assignment **until the enclosing scope exits**.

It is commonly used for:
* Resource cleanup (freeing memory, closing files, closing connections).
* State restoration (unlocking mutexes, clearing flags).
* Ensuring code always executes regardless of exit path (`return`, early errors, loop exits).

Syntax:
```gg
defer cleanup(resource)
defer state = 0
```

### 3.2 Execution Order (LIFO - Reverse Order)

When multiple `defer` statements exist in the same scope, they run in **LIFO (Last-In, First-Out)** order. The most recently declared `defer` executes first when the scope exits:

```gg
fn test_order():
    defer print("3. Declared last, executes FIRST")
    defer print("2. Declared in the middle, executes SECOND")
    defer print("1. Declared first, executes LAST")
    print("Normal body executing...")

# Output:
# Normal body executing...
# 3. Declared last, executes FIRST
# 2. Declared in the middle, executes SECOND
# 1. Declared first, executes LAST
```

> **Argument Evaluation Timing (Zig-style):** In Greengold, deferred arguments are evaluated at scope exit when the statement executes.

### 3.3 Early Exits (`return`, `break`, `continue`)

`defer` runs on all scope exit paths:
* **On `return` statements:** All active `defer` blocks execute just before the function returns its value.
* **In loops (`for`, `while`):** Deferred statements in a loop block execute at the end of each iteration or when exiting via `break` / `continue`.

```gg
fn search(n: i32) -> i32:
    defer print("search() is ending")
    
    if n > 0:
        defer print("Exiting positive branch")
        return n * 2   # Prints 'Exiting positive branch' first, then 'search() is ending'
        
    return 0
```

### 3.4 Interaction with Automatic `drop`

In Greengold, heap-owning objects (`Box[T]`, `List[T]`) are automatically freed (`drop`ped) by the compiler at scope exit.

`defer` executes **BEFORE automatic drop of owning variables**. This guarantees that variables referenced in deferred statements remain live and valid:

```gg
fn cleanup_demo():
    v = List[i32]()
    defer print("Final length of vector:", v.len) # v has not been dropped yet!
    v.push(10)
    v.push(20)
    # 1. defer runs (v.len read -> 2)
    # 2. v is automatically dropped (no memory leaks)
```

### 3.5 Rules and Constraints

1. **Calls and assignments only:** `defer` must be followed by a function/method call or an assignment. A bare value (`defer 5`) is invalid.
2. **`?` operator is disallowed:** Writing `defer f()?` is prohibited, because `?` generates an early return, and initiating an early return during scope cleanup could cause undefined behavior.

---

## 4. Stored references and `-> ref` / `-> lend`

### 4.1 What a reference is

`read T` and `lend T` are the same representation as a reference parameter: a non-owning `T*`. The pointer is not dropped. It can be a parameter, a local, or a struct field.

```gg
struct Person:
    name: string
    age: i32

r: read Person = hero
w: lend Person = hero
n = name_of(hero)       # the right-hand side is already a pointer; the mode is inferred

struct Slot:
    who: read Person tied to self
```

`name: string` makes `Person` heap-owning, so a by-value parameter is already rewritten to `read`. A Copy struct (only numbers, `bool`, `str`) must be written `p: read Person` before a pointer to it can be returned. `x = hero` is unchanged: Copy copies, Move transfers ownership. `x: List[i32] = bag.get(0)` asks for an owned value and still rejects the view.

Assigning a reference variable reties the pointer (`w = other`), unless it is `fixed`. It does not make a `read` pointee mutable. Mutation goes through the pointee (`w.age = 1`) and requires `lend`.

### 4.2 One-parameter origin

Returning a pointer is only sound when the pointee outlives the call. Greengold does not add `'a`. The rule is:

> **Every `return` in a `-> ref T` or `-> lend T` function must be a place derived from the same `read` or `lend` parameter.**

That place may be the parameter, a field, an index, `p.get(i)`, or a reference local tied to that parameter. It does not have to be the first parameter. When the body could come from more than one parameter, name the tie:

```gg
fn pick(a: read Person, b: read Person) -> ref Person tied to b:
    return b
```

`-> lend` must come from a `lend` parameter. A by-value or `consume` parameter is not a valid origin: its slot dies on return. `tied to` cannot name a local.

```gg
fn bad_local(p: read Person) -> ref i32:
    x = 1
    return x            # ERROR: a local would dangle

fn bad_value(a: i32) -> ref i32:
    return a            # ERROR: `a` is not `read` or `lend`

fn bad_none() -> ref i32:
    return 1            # ERROR: at least one parameter is required
```

### 4.3 Why no Rust-style lifetimes (`'a`)?

The tie is the root variable of the place, not a named lifetime. The borrow checker rejects moving, reassigning, or `lend`ing that root while a reference tied to it is still used. `read` allows other reads. `lend` allows no other access while the holder is used later. A reference whose root is declared in an inner scope cannot be stored in an outer variable or returned.

### 4.4 What a stored reference may do

**Permitted:**
* Read it: `print(r.age)`, `print(get_name(hero))`.
* Store the pointer: `n = get_name(hero)`.
* Pass it as `read`, or mutate through it when it is `lend`.
* Retie a reference variable (not `fixed`) to another place that lives long enough.

**Rejected:**
* Storing a heap view as an owned value: `x: string = get_name(hero)`.
* `consume` of the reference itself. Ownership moves only from the owning place, and only when no live reference is tied to it.
* Mutating through `read`.
* Returning or storing a pointer to a local or to an inner-scope owner.

A reference is never dropped, so it cannot double-free the owner.

### 4.5 Built-in Example: `List[T].get(i)`

Greengold's dynamic array `List[T]` provides two ways to access elements:
1. `v[i]`: Direct value copy for primitive (Copy) types.
2. `v.get(i)`: Acquires a **bounds-checked `ref T` view** without moving ownership:

```gg
v = List[string]()
v.push("Greengold")
v.push("Systems Language")

# get(i) returns a `ref string` without copying heap data:
print(v.get(0))
print("Length:", v.get(0).len)
```

If index `i` is out of bounds, the program safely aborts in both Debug and Release modes via `_gg_panic_bounds` with exit code 101.

---

## 5. Related System Mechanisms ("vs.")

### 5.1 Parameter Modes: `read`, `lend`, and `consume`

In Greengold, parameter ownership and access models are divided into three modes:

| Mode | Syntax (Signature) | Call Site | Memory Semantics |
|---|---|---|---|
| **Read** | `p: T` | `f(x)` | Value is copied or passed read-only. `p` cannot be mutated. |
| **Lend** | `p: lend T` | `f(x)` | Mutable reference (`T *`). `x` cannot be `fixed`. |
| **Consume** | `p: consume T` | `f(x)` | Move semantics. `x` cannot be used afterwards (moved). |

#### Alias Checking:
The same variable cannot be passed to a function simultaneously as `lend` and read, or as two `lend` parameters (modes come from the signature of `f`):
```gg
f(a, a)       # f(x: lend T, y: lend T): COMPILE ERROR, conflicting lend access
f(a, a)       # f(x: lend T, y: T):      COMPILE ERROR, simultaneous read and mutation
f(a.x, a.y)   # f(x: lend T, y: lend T): VALID, distinct non-overlapping fields
```

### 5.2 Heap Memory (`Box[T]`, `List[T]`) and Automatic `drop`

In Greengold, recursive data structures (trees, linked lists) and dynamically sized data live on the heap:
* `Box[T]`: Allocates a single value on the heap. Value accessed via `b.value`.
* `List[T]`: Dynamically resizing array with `push`, `pop`, `clear`, `.len`, and `.get(i)` methods.

```gg
enum LinkedList:
    Cons(i32, Box[LinkedList])
    Nil

fn main():
    # Box and List are owning types; storing `tail` in a new owner moves it:
    tail = LinkedList.Nil
    head = LinkedList.Cons(1, Box[LinkedList](tail))
    # When main exits, head and all nested Boxes are automatically DROPPED.
```

The compiler tracks a runtime liveness flag (`_gg_live_x`) for each owner variable. If moved, the flag becomes `false`. At scope exit, only active instances are freed (zero leaks, zero double-frees).

### 5.3 `if` and `match` as Expressions

In Greengold, both `if` and `match` can be used either as statements or as value-producing **expressions**:

```gg
# if-then-else as expression:
max_val = if a > b then a else b

# match as expression:
status_code = match response:
    Ok(code) => code
    Err(_)   => -1
```

All arms must evaluate to the exact same type. In `match` expressions, full exhaustiveness is verified at compile time.

### 5.4 Error Handling: `?` Operator, `Optional`, and `Result`

`Optional[T]` and `Result[T, E]` in the prelude are standard generic enums defined directly in Greengold in `greengold/core/core.gg`:

```gg
enum Optional[T]:
    Some(T)
    None

enum Result[T, E]:
    Ok(T)
    Err(E)
```

The `?` operator unwraps the success value or returns early with the error/none variant:

```gg
fn parse_number(s: string) -> Result[i32, string]:
    ...

fn calculate() -> Result[i32, string]:
    # If parse_number returns Err, calculate() immediately returns that Err:
    n1 = parse_number("10")?
    n2 = parse_number("20")?
    return Ok(n1 + n2)
```

---

## 6. Comparative Summary Table

| Feature | Greengold | Rust | Go | C99 |
|---|---|---|---|---|
| **Feature / Interface** | Structural (No explicit `impl`, static) | Explicit `impl`, static and dynamic (`dyn`) | Structural (`interface{}`), dynamic | None |
| **Feature Dispatch** | Static only (Monomorphization) | Static and dynamic vtable | Dynamic itable only | None |
| **`defer`** | Yes (LIFO, Zig-style evaluation, runs before drop) | None (Uses `Drop` feature) | Yes (LIFO, function-scoped) | None |
| **Reference / View** | `read`/`lend` stored as `T*`; `-> ref`/`-> lend` tied to one parameter | `&'a T` (Explicit lifetime annotations) | Raw pointer (`*T`), GC tracked | Raw pointer (`T *`), unchecked |
| **Memory Management** | Value copy + Heap ownership (`Box`/`List`) + Auto Drop | Ownership + Borrow checker + Drop | Garbage Collector (GC) | Manual (`malloc`/`free`) |
| **Immutability** | Default mutable; opt-in `fixed`, inferred `fixed` shown as a hint | Default immutable; opt-in via `mut` | Default mutable | `const` qualifier |
| **Compilation Target** | LLVM IR / Native code | LLVM IR / Machine code | Machine code | Direct native compiler |
