# Greengold

Greengold (`.gg`) is a statically typed, indentation-sensitive language compiled to machine code through LLVM. This file is the language a program must follow. One example is given for each feature. This file is normative: when it and the compiler disagree, the compiler has a bug. `conformance/` holds a program for each example here and for each rejected form, with the output or the diagnostic code it must produce. `gg check --json` is the diagnostic interface, and `gg api --json` is the library interface. A package names its edition in `gg.toml` (`edition = "2026"`); `docs/STABILITY.md` says what may change within an edition.

There is one way to write each construct. A call does not repeat the parameter mode. `else if` is not a keyword. `own` is not a keyword. `//` is not a comment.

## 1. A program

A file is a sequence of top-level declarations: `struct`, `enum`, `feature`, `impl`, `fn`, `test`, `const`, `extern`, `import`, `type`, `comptime fn`, and `hot fn`. Other statements live inside a function. An executable has `fn main():` with no parameters and no result.

Indentation is four spaces. A tab is a syntax error. A block opens with `:` and the next line indents by exactly four. A comment starts with `#` and runs to the end of the line. A block comment starts with `#[` and ends with the matching `]#`; it can span lines, sits inside a line, and nests. One statement per line.

```gg
# The entry point. print writes its arguments and a newline.
fn main():
    print("Hello, Greengold")
```

## 2. Names, types, and literals

Names are letters, digits, and `_`. Type parameters start with an uppercase letter. Primitive types are `i8 i16 i32 i64 i128 isize`, `u8 u16 u32 u64 u128 usize`, `f16 f32 f64`, `bool`, and `str`. `i128` and `u128` are 128-bit integers (division needs the compiler runtime library, which hosted targets have). `f16` is IEEE half precision: it is stored in 16 bits and every operation converts to `f32` and back with integer code, so it needs no runtime library; a value rounds to 11 significant bits and overflows to infinity above 65504. `int` means `i32`, `uint` means `u32`, `float` means `f32`, and `double` means `f64`, except in a bounded integer (section 12), where the word `int` means `i64`.

There is no `char` type. A character literal such as `'A'` or `'\n'` has type `u8`. A string literal has type `str`, a read-only view of bytes. `true` and `false` are `bool`. Integers may use `_` separators and `0x` or `0b` prefixes. A float literal has a decimal point or an exponent (`2.5`, `1e9`, `6.02e-23`) and defaults to `f64`.

`null` is a pointer literal. Its type comes from the place it is stored in. It is not a keyword.

```gg
fn main():
    n: i32 = 1_000
    bits: u8 = 0b1111
    pi: f64 = 3.14
    letter: u8 = 'A'
    text: str = "gg"
    flag: bool = true
    print(n, bits, pi, letter, text, flag)
```

An interpolated string is `f"..."` or `f"""..."""`. `{expr}` is replaced; `{{` and `}}` are braces. The result is a `string`. `{expr:format}` formats the value: `[[fill]align][+][#][0][width][.precision][type]`. A width pads to that many characters, numbers to the right and everything else to the left; `<`, `>`, and `^` align left, right, or centered, after an optional fill character (`{name:-^9}`). `0` pads a number with zeros after its sign (`{n:05}`), and `+` writes the sign of a positive number. A precision is the number of decimals of a float (`{x:.2}`, rounded half away from zero). The type `x`, `X`, `b`, or `o` writes an integer in base 16, 2, or 8, and `#` adds `0x`, `0b`, or `0o`; `e` or `E` writes a number with an exponent (`1.23e+04`, six decimals unless a precision is given); `d` is a plain integer. A format that does not fit the value is an error.

```gg
fn main():
    name = "gg"
    print(f"hello {name}")
    print(f"[{3.14159:.2}] [{42:>5}] [{255:#x}] [{name:-^6}]")
```

Some words are names except in the form that uses them. `let` is read after `if` or `while`. `step` is read in a counted loop. `as` is read at the end of `import` or `extern`. `to` is read after `tied`. `type` starts an alias. `test` starts a top-level test block. `require` is a statement. `overflow` and `wrapping` are arithmetic modes. `ref` is read in `-> ref`. `mut` is read in `*mut`. Anywhere else, those spellings are ordinary names.

## 3. Bindings

A variable can be changed. `name = expr` infers the type. `name: T = expr` writes the type. Assignment uses `=`, `+=`, and the other update operators. There is no `++`.

`fixed name = expr` (or `fixed name: T = expr`) declares a variable that never changes: assigning it, lending it, or calling a method that changes it is an error. A variable that nothing changes is treated as `fixed`, so writing the word only adds a guarantee. Editors show the inferred `fixed` as an inlay hint. `var` is no longer used; it stays reserved, and writing it is an error that says to delete it.

```gg
fn main():
    fixed limit = 10
    x = 5
    y = 5
    y = 6
    y += 1
    print(x, y, limit)
```

## 4. Functions

A function is `fn name(params) -> T:` followed by an indented body. Omit `-> T` when the function returns nothing. Every path of a function that returns a value must `return` that value. Arguments are expressions. The call is `f(x)`, never `f(consume x)`.

```gg
fn add(a: i32, b: i32) -> i32:
    return a + b

fn main():
    print(add(2, 3))
```

### Parameter modes

The mode is written once, on the parameter.

- `p: T` with a copyable `T` (section 5) passes a copy. The parameter is immutable inside the function. This is not the same as `read`.
- `p: read T` is a shared borrow. The function may read `p` and may not assign to it. Other reads of the same memory may exist.
- `p: lend T` is an exclusive borrow. The argument must be a variable that is not `fixed` (or already `lend`). The function may assign through it. No other `read`, `lend`, or `consume` of that memory is allowed in the same call.
- `p: consume T` takes ownership. After the call the argument is gone.

`read place` and `lend place` are expressions. They create a reference. They are not written at a call.

```gg
struct Counter:
    value: i32

fn show(c: Counter):
    print(c.value)

fn bump(c: lend Counter):
    c.value += 1

fn finish(c: consume Counter):
    print(c.value)

fn main():
    c = Counter{ value: 1 }
    bump(c)
    show(c)
    finish(c)
```

`exclusive` on a `read` or `lend` parameter tells the compiler that this reference does not overlap another parameter. It does not change the mode.

```gg
fn fill(n: exclusive lend i32):
    n = 1

fn main():
    n = 0
    fill(n)
    print(n)
```

### Tests

A `test` block is a top-level declaration. It belongs to the nearest function above it. `test:` takes that function's name. `test negatives:` adds the name you write. The body is ordinary code, indented four spaces. `require` stops that test when the condition is false. `fn test_name():` with no parameters and no result is also a test. `fn main` does not run either form. `gg test` runs both.

```gg
fn add(a: i32, b: i32) -> i32:
    return a + b

test:
    require add(2, 3) == 5

test negatives:
    require add(-1, 1) == 0

fn main():
    print(add(2, 3))
```

### Attributes

An attribute is a line `@name` or `@name(args)` directly above a `fn`, a method in an `impl`, a `struct`, or a struct field. The compiler checks the use and records it, and a tool or a code generator acts on it: network stubs, serialization tables, editor metadata. An attribute can also say what it requires, in code: see the body below.

An attribute must be declared first, so a misspelled one is an error. `attribute name(param: kind, ...)` lists the parameters. A kind is `str`, `int`, `float`, `bool`, or `ident` (a bare name such as `server`). `= value` makes a parameter optional. `on fn, struct, field` limits where the attribute may go; without it, anywhere. Arguments are positional or `key=value`, and are literals or bare names, never expressions. An attribute may be written once per item.

The compiler gives these built-in attributes a meaning (they need no `attribute` line): `@inline(always)`, `@inline(never)`, `@inline(hint)` and `@cold` guide the optimizer; `@naked` leaves out the prologue and epilogue (the body is inline `asm`); `@section("name")` puts a function or a `static` in a linker section; `@used` keeps a symbol even when nothing refers to it; `@weak` makes it a weak symbol that another definition may replace; `@align(n)` aligns a `static`; `@export("name")` gives a function or `static` the plain C symbol `name` (the function's own name when `name` is left out), so a linker script or C code can find it, and its signature should use only numbers and pointers; `@interrupt` and `@interrupt("kind")` export the function under its own name for an interrupt table (the kind, such as `IRQ` or `machine`, becomes the LLVM `interrupt` attribute where the target has one); `@panic_handler` marks `fn on_panic():` as the function that runs when the program panics, after the message (hosted) or instead of the plain trap (`--no-std`). Attributes on a `static` go on the line above `static`.

```gg
attribute replicated(mode: ident, reliable: bool = false) on fn
attribute notify(callback: str) on field

struct Player:
    @notify("on_health")
    health: i32

impl Player:
    @replicated(server, reliable=true)
    fn hit(self: lend Self, amount: i32):
        self.health -= amount

fn main():
    p = Player{ health: 10 }
    p.hit(3)
    print(p.health)
```

A declaration may end in `:` and a body. The body is `comptime` code that runs while compiling, once for each use. It sees the arguments as variables (an `ident` is a `str`, an `int` an `i64`, a `float` an `f64`) and four `str` values about the item: `target_kind` (`fn`, `struct`, or `field`), `target_name`, `target_owner` (the struct of a method or field, else empty), and `target_type` (the result type of a function or the type of a field, else empty). `compile_error(message)` rejects the use: the error points at the `@name` line and carries the message. `compile_error` is only for this body, and the body follows the rules of `comptime fn` (no I/O, no heap).

```gg
attribute range(min: int, max: int) on field:
    if min > max:
        compile_error("min is bigger than max")
    if target_type != "i32":
        compile_error(f"@range is for i32 fields, not {target_type}")

struct Slider:
    @range(0, 100)
    volume: i32

fn main():
    s = Slider{ volume: 50 }
    print(s.volume)
```

`gg attrs file.gg` type-checks the program and writes every attributed item as JSON: its kind, name, owner, file and line, parameter types and modes, and each attribute with its arguments resolved to parameter names and defaults filled in.

## 5. Copy and move

Numbers, `bool`, `str`, raw pointers, and structs and enums that do not contain `Box`, `List`, `string`, a `std.thread` handle, or a type with `drop` (section 7) are copied. Copying a struct copies its fields. `consume` on a number, `bool`, or array of numbers is an error.

`Box`, `List`, `string`, and any struct or enum that contains one of them are moved. They are freed at the end of their scope, including on `return`, `break`, `continue`, and `?`. A bare parameter of a move type gets its mode from the body: `read` when the body only reads it, `lend` when the body changes it, and `consume` when the body moves it. The caller sees that mode: a `lend` argument cannot be `fixed`, and a `consume` argument is moved. Write the mode to fix it in the signature. Storing a moved place in a new owner (`a = b`, a field, a `return`) moves it. A fresh value (a call or a constructor) is already a new owner, so it is not marked moved at the source. `copy place` copies a copyable place. It is rejected for a heap value. `x.clone()` is a deep copy of any value: heap parts get new allocations. A type that defines `clone` uses its own. A value that holds a `lend` reference cannot be cloned.

A moved place cannot be used again. A field of a heap value cannot be moved on its own. A `read` or `lend` parameter cannot be consumed; a copyable by-value parameter can, because it is the function's own copy. Two `lend`s of the same memory cannot be passed in one call.

```gg
fn main():
    n = 3
    m = copy n
    print(n, m)
```

```gg
fn take(xs: consume List[i32]):
    print(xs.len)

fn main():
    xs = List[i32]()
    xs.push(1)
    take(xs)
```

## 6. Statements

`if`, `elif`, and `else` open blocks. The condition is `bool`. A block is indented on the lines after the `:`, or is one simple statement on the same line after it: `if x > 0: return 1`, `for i in 0..3: total += i`, and a `match` arm such as `Leaf(v): return v`. A statement that opens a block of its own (`if`, `while`, `for`, `match`) cannot follow the `:` on the same line. The keyword is `elif`, not `else if`. `while` repeats while the condition is true. `break` and `continue` affect the innermost loop, including when they appear inside `match`. `pass` is an empty statement. `require cond` stops the program when `cond` is false. When `cond` compares two numbers, `bool` values, or `str` values (`require a == b`, `<`, `<=`, `>`, `>=`, `!=`), the message shows both sides: `require condition failed: add(2, 3) == 4 (left: 5, right: 4)`.

```gg
fn main():
    n = 0
    while n < 3:
        if n == 1:
            n += 1
            continue
        n += 1
    require n == 3
    print(n)
```

`for i in lo..hi:` visits `lo, lo+1, ...` and stops before `hi`. `lo..=hi` includes `hi`. `step k` changes the stride; a negative step needs a signed integer. `for i in n:` visits `0 .. n`. The counter has the type of the bounds: `0..4` counts in `i32`, `0..xs.len` in `usize`. An integer index converts to `usize` in an index position (`xs[i]`). A counter whose bounds are constants (`for i in 0..10:`) also converts to any integer type that holds every value it takes, so `total += i` works when `total` is an `i64` or a `usize`, and `i < xs.len` compares. Other mixes follow section 12. `for i in range(n):` is the same as `for i in n:`. `for x in place:` visits the elements of an array, a slice, a `List`, or a `str`. `for i, x in place:` also binds the `usize` index. `for x in place:` borrows each element as `lend` when the place is mutable.

```gg
fn main():
    total = 0
    for i in 0..4 step 2:
        total += i
    print(total)
```

`for i, x in place:` binds the `usize` index and the element. The index comes first.

```gg
fn main():
    xs: [3]i32 = [10, 20, 30]
    total = 0
    for i, x in xs:
        total += i32(i) + x
    print(total)
```

`defer` runs a call or an assignment when the enclosing block ends, including on `return`, `break`, and `continue`. Later defers run first. `defer` does not accept `?`.

```gg
fn main():
    defer print(2)
    print(1)
```

## 7. Structs, methods, enums

A struct names its fields and their types. A literal writes every field: `Name{ field: expr }`. Methods are declared inside `impl Name:`, not as `fn Name.method`. The first parameter is the receiver. Bare `self` means `self: Self`. A method with no receiver is called as `Type.name(...)`; on a generic type the arguments are written: `Pair[i32, str].new()`, `thread.Queue[i32].new()`.

A method with the operator's name is that operator. `+` is `add`. Binary `-` is `sub`. Unary `-` is `neg` and takes no extra argument. `*` is `mul`, `/` is `div`, `%` is `rem`, `&` is `bitand`, `|` is `bitor`, and `^` is `bitxor`. `==` is `eq`. `!=` is `not` applied to `eq`. A type without `eq` still has `==` (section 13). `<` is `lt`, `<=` is `le`, `>` is `gt`, and `>=` is `ge`. A comparison method returns `bool`. Defining `lt` does not define `>`. An enum takes methods in `impl Name:` the same way. A generic impl repeats the parameters: `impl Pair[A, B]:`.

```gg
struct Vec:
    x: i32

impl Vec:
    fn add(self, other: Vec) -> Vec:
        return Vec{ x: self.x + other.x }

fn main():
    c = Vec{ x: 1 } + Vec{ x: 2 }
    print(c.x)
```

```gg
struct Pair[A, B]:
    first: A
    second: B

impl Pair[A, B]:
    fn swapped(self) -> Pair[B, A]:
        return Pair[B, A]{ first: self.second, second: self.first }

fn main():
    p = Pair[i32, str]{ first: 1, second: "a" }.swapped()
    print(p.second)
```

An enum has one or more variants. A variant is `Name` or `Name(T, U)` with positional fields. Construct it as `Enum.Name` or `Enum.Name(expr)`. `Valid`, `None`, `Ok`, and `Err` are the short forms of the prelude enums. In a pattern a bare name is a variant, not a new variable. `_` ignores a payload or catches the rest. A `match` must cover every variant, or end with `_`. An arm body is a block; an empty arm is an error, so write `pass`. When no variant carries a payload, each variant has a number: its position from 0, or the one written after it (`Red = 1`); a variant without a number follows the one before it, and two variants cannot share a number. Such an enum gets `e.to_int() -> i64` and `Enum.from_int(n) -> Optional[Enum]` (unless the program defines them), and `i32(e)` converts it to its number, as C enums do.

`match e:` reads. `match lend e:` mutates the value in place; `e` must be addressable. `match consume e:` moves `e` into the match.

```gg
enum Shape:
    Circle(i32)
    Empty

fn main():
    s = Shape.Circle(3)
    match lend s:
        Circle(r):
            r = 4
        Empty:
            pass
    match s:
        Circle(r):
            print(r)
        Empty:
            print(0)
```

`match` also accepts an integer, `u8` (from a character literal), `bool`, or `str`. Arms may be literals, `|` alternatives, or inclusive and exclusive ranges. `_` covers the rest.

```gg
fn label(n: i32) -> i32:
    match n:
        0 | 1:
            return 1
        2..=4:
            return 2
        _:
            return 0

fn main():
    print(label(3))
```

An arm may end with a guard: `pattern if condition:`. The arm runs only when the pattern fits and the condition is `true`; otherwise the next arms are tried. The condition sees the arm's names. `name if condition:` matches every value and names it (the value is read, not moved), unless `name` is a variant of the matched enum. A guarded arm does not count when the compiler checks that every case is covered, so a guarded arm needs an unguarded arm or `_` after it. In `match consume`, the payload moves into the names only when the guard is `true`.

```gg
fn sign(n: i32) -> str:
    match n:
        0:
            return "zero"
        v if v < 0:
            return "negative"
        _:
            return "positive"

fn main():
    o: Optional[i32] = Valid(12)
    match o:
        Valid(x) if x > 10:
            print("big", x)
        Valid(x):
            print(x)
        None:
            print(sign(-3))
```

A destructor is `fn drop(self: lend Self)` inside `impl Name:`. It takes no other parameter and returns nothing. It runs once, when the owner goes away (the end of its scope, a `return`, `break`, `continue`, `?`, or the end of the function a `consume` parameter was moved into), and then the fields are freed. Owners go away in reverse order of declaration. A type with `drop`, and any type that holds one, is moved and not copied. `drop` cannot be called by hand. `clone` of such a value is rejected unless the type defines its own `clone`. `match consume` cannot take it apart.

```gg
struct Fd:
    n: i32

impl Fd:
    fn drop(self: lend Self):
        print(f"close {self.n}")

fn main():
    a = Fd{ n: 1 }
    b = Fd{ n: 2 }
    print("work")
```

`union Name:` lists fields like a struct, but they share one place in memory: the union is as large as its largest field. A literal sets exactly one field (`Bits{ f: 1.0 }`). Reading or writing a field is inside `unsafe:`, because the bytes may have been written as another field. A field holds plain data (numbers, `bool`, pointers, arrays, and structs of them); a union is copied and does not print. `packed struct Name:` has no padding between its fields, so a field may be misaligned (alignment 1). `align(N) struct Name:` has at least alignment `N`, a power of two up to 64, and a size that is a multiple of `N`; use it to keep data on its own cache line or to meet a hardware rule.

```gg
union Bits:
    f: f32
    u: u32

packed struct Header:
    tag: u8
    len: u32

align(64) struct Slot:
    hits: i64

fn main():
    x = Bits{ f: 1.0 }
    unsafe:
        print(x.u)
    print(size_of[Header](), align_of[Slot]())
```

`match consume e:` moves `e` before the arms run. Use it for a heap payload.

```gg
fn main():
    n: Optional[i32] = Valid(3)
    match consume n:
        Valid(v):
            print(v)
        None:
            print(0)
```

## 8. Generics and features

A generic declaration lists its type parameters in brackets: `struct Pair[A, B]`, `fn id[T](x: T) -> T`. A type writes the arguments: `Pair[i32, str]`. A struct literal may leave them out when the field values show every parameter, or when the expected type gives them: `Pair{ first: 1, second: "a" }` is a `Pair[i32, str]`. A generic body is checked where it is declared, against its bounds: it may call only the methods of its feature bounds and use only the operators and conversions its builtin bounds allow, so `fn max[T](a: T, b: T)` cannot use `a > b` without `T: Ord`. It is checked again at each instantiation, where the ownership rules of the real type apply.

```gg
fn id[T](x: T) -> T:
    return x

fn main():
    print(id[i32](7))
```

```gg
struct Pair[A, B]:
    first: A
    second: B

fn main():
    p = Pair{ first: 1, second: "a" }
    print(p.first, p.second)
```

A parameter written with an integer type instead of bounds is a constant parameter: `fn total[N: usize](xs: [N]i32)`, `struct Grid[W: usize, H: usize]`. Its argument is a number (`Grid[2, 3]`, `total[3](xs)`), or it is read off the length of an array argument or field. Inside the declaration it is an array length (`[N]T`) and a constant of its type (`for i in 0..N`). Each distinct value makes its own copy of the code, as each type does. A constant parameter is not a type, and a type parameter does not take a number.

```gg
fn total[N: usize](xs: [N]i32) -> i32:
    s = 0
    for x in xs:
        s += x
    return s

struct Grid[W: usize, H: usize]:
    cells: [W][H]i32

impl Grid[W, H]:
    fn area(self) -> usize:
        return W * H

fn main():
    g = Grid{ cells: [[1, 2, 3], [4, 5, 6]] }
    print(total([1, 2, 3]), g.area(), total[2]([4, 4]))
```

A `feature` is a set of method signatures, with optional default bodies. `Self` is the implementing type. A struct or enum satisfies the feature when it has every method that has no default body, with the same arity and modes. It does not write `impl Feature for Type`. Default methods are then available; a method written on the type replaces the default. A bound is resolved at compile time; `dyn Feature` (below) chooses the method when the program runs.

Use a feature as a bound: `fn show[T: Describable](x: T)` or `struct Box[T: Num + Ord]`. Built-in bounds are `Num`, `Int`, `Float`, `Ord`, `Eq`, `Copy`, and `Key`. `Ord` is numbers and text (`str`, `string`). `Eq` is any type `==` accepts (section 13). `Copy` is any type that is copied, not moved (section 5). `Key` is what a hash map key needs: a type that `hash` and `==` accept, which leaves out floats (section 13), or a type with `fn hash(self: Self) -> u64` and `fn eq(self: Self, other: Self) -> bool`.

```gg
feature Named:
    fn name(self: Self) -> str

struct Item:
    title: str

impl Item:
    fn name(self) -> str:
        return self.title

fn announce[T: Named](x: T):
    print(x.name())

fn main():
    announce[Item](Item{ title: "gem" })
```

A method body written in the feature is the default. The type does not repeat it. A method of the same name on the type replaces the default. A feature method cannot have its own type parameters.

```gg
feature Sized:
    fn size(self: Self) -> i32
    fn twice(self: Self) -> i32:
        return self.size() + self.size()

struct Gem:
    n: i32

impl Gem:
    fn size(self) -> i32:
        return self.n

fn main():
    print(Gem{ n: 3 }.twice())
```

`dyn Feature` is an owned value of any type that satisfies the feature, so values of different types can share one list. A value converts by itself where a `dyn Feature` is expected (a declaration, a parameter, `push`); it moves into the `dyn` value, which keeps it on the heap with a table of its methods, and frees it (running its `drop`) when the `dyn` value goes away. A method is called through the table. It can be called when it takes `self` as a copy, `read`, or `lend`, does not mention `Self` in another parameter or the result, and does not take a moved value or return a reference; default methods of the feature count. A type that holds a view (a `str`, a slice, or a reference field) cannot become a `dyn` value, a `dyn` value is moved and not copied, and it is not cloned or printed. Use a bound when every value has one type: it costs nothing at run time.

```gg
feature Shape:
    fn area(self: Self) -> f64
    fn grow(self: lend Self, by: f64)

struct Square:
    side: f64

impl Square:
    fn area(self) -> f64:
        return self.side * self.side

    fn grow(self: lend Self, by: f64):
        self.side += by

struct Ring:
    sizes: List[f64]

impl Ring:
    fn area(self) -> f64:
        total = 0.0
        for s in self.sizes:
            total += s
        return total

    fn grow(self: lend Self, by: f64):
        self.sizes.push(by)

fn main():
    shapes = List[dyn Shape]()
    shapes.push(Square{ side: 2.0 })
    shapes.push(Ring{ sizes: List[f64]() })
    for s in shapes:
        s.grow(1.0)
    for s in shapes:
        print(s.area())
```

## 9. Optional, Result, and `?`

`Optional[T]` is `Valid(T)` or `None`. `x = None` takes its type from the first later `x = Valid(v)`, or from a place that expects an `Optional[T]` (`f(x)`, `return x`); with no such use, write the type: `x: Optional[i32] = None`. `Result[T, E]` is `Ok(T)` or `Err(E)`. They live in the prelude, which is prepended to every program. `has_value`, `is_none`, `is_ok`, `is_err`, `value_or`, and `value_or_panic` read a copy of the payload. Do not use them on a heap payload; use `match consume` instead.

`?` follows a whole expression in exactly four places: `x = f()?`, `x = f()?`, `return f()?`, and a statement `f()?`. The enclosing function must return the same kind of enum. For `Result`, the error types must match, or the target error type must have `Type.from(e: Source) -> Type`. `?` on `None` or `Err` returns from the function.

```gg
fn half(n: i32) -> Optional[i32]:
    if n < 0:
        return None
    return Valid(n)

fn twice(n: Optional[i32]) -> Optional[i32]:
    v = n?
    return Valid(v + v)

fn main():
    print(twice(half(4)).value_or(0))
```

```gg
fn div(a: i32, b: i32) -> Result[i32, str]:
    if b == 0:
        return Err("zero")
    return Ok(a / b)

fn run() -> Result[i32, str]:
    q = div(8, 2)?
    return Ok(q)

fn main():
    print(run().value_or_panic())
```

`if let Pattern = expr:` and `while let Pattern = expr:` are the one-arm forms. `if let` may end with `else:`. It does not take `elif`. `while let` is useful with `List.pop`, which returns `Optional[T]`.

```gg
fn main():
    items = List[i32]()
    items.push(1)
    while let Valid(top) = items.pop():
        print(top)
    n: Optional[i32] = Valid(4)
    if let Valid(v) = n:
        print(v)
    else:
        print(0)
```

## 10. Heap, text, arrays, slices

`List[T]()` is an empty owned list. `push`, `pop`, `clear`, `swap(i, j)`, `swap_remove(i)`, `remove(i)`, and `insert(i, x)` require a list that is not `fixed`. `pop` returns `Optional[T]`; `swap_remove(i)` (moves the last element into the gap) and `remove(i)` (keeps the order) return the element. `reserve(n)` makes room for `n` more elements in one allocation, so the next `n` pushes do not reallocate; a size the machine cannot allocate stops the program. `resize(n, x)` sets the length to `n`: a longer list gets copies of `x` appended in one allocation (a byte list is filled with `memset`), a shorter one is cut. It needs copied elements (numbers, `bool`, `str`, plain structs), not moved ones. `truncate(n)` keeps the first `n` elements, frees the rest, and does nothing when `n >= len`. Positions are bounds-checked; `insert` accepts `i == len`. `.len` is a `usize`; `.len()` is the same length, on a list, an array, a slice, a `str`, and a `string`. `xs[i]` is bounds-checked. It is a place inside the list: it can be read, changed through a list that is not `fixed` (`xs[i].push(1)`, `xs[i] = v` frees the old element), and passed as `read` or `lend`. It cannot be moved out; use `xs[i].clone()` or `pop`. `get(i)` returns `ref T`.

A list of copied elements also has these methods, written in Greengold in the Core library. `map(f)` returns a new list of `f(x)`; `filter(f)` keeps the elements where `f(x)` is `true`; `fold(init, f)` combines them from the left with `f(acc, x)`. `any(f)`, `all(f)`, and `count(f)` test every element. `find(f)` returns the first matching element and `position(f)` its index, as `Optional`. `contains(x)` and `index_of(x)` compare with `==` (`T: Eq`). `sum()` adds the elements (`T: Num`); `min()` and `max()` return `Optional[T]` (`T: Ord`), and so do `first()` and `last()`. `is_empty()` tests the length. On a list that is not `fixed`, `reverse()` reverses it, `extend(other)` appends copies of another list's elements, `sort()` orders it ascending (`T: Ord`), and `sort_by(before)` orders it with a function that says whether `a` goes before `b`. Sorting is in place, uses no extra memory, and is not stable. A callback is a lambda or a function of one element by value: `xs.map(fn(x: i32) -> i32 => x * 2)`. A list of moved elements (`string`, `List`) does not have the methods that copy elements out; walk it with `for`.

`Box[T](value)` owns one heap value. Read and write `.value`.

The heap comes from the C library unless the program names its own functions with a top-level `allocator alloc, resize, free` line: `fn alloc(size: usize) -> *mut u8`, `fn resize(p: *mut u8, size: usize) -> *mut u8` (with `p == null` it allocates), and `fn free(p: *mut u8)`. Then every `Box`, `List`, `string`, `Shared`, `Arc`, `Fn`, and `dyn` value is allocated through them, and a `--no-std` program can use the heap. A result of `null` stops the program as out of memory. A program has at most one `allocator`.

`Shared[T](value)` is a heap value with several owners. `s.clone()` adds an owner and copies no data; the value is freed when the last owner goes away. `.value` can be read but not changed or moved out, because other owners see the same value. The count is not atomic: a `Shared` value is not for passing between threads. `Arc[T](value)` is the same with an atomic count, so its owners may live on different threads (section 16).

`string` is an owned growable buffer (`List[u8]` underneath). `str` is a view. `"..."`, indexing, and `s.len` use `str`. `string.new()` is empty. `string.from(text)` and `text.to_string()` build an owned string. On a string that is not `fixed`, `append_str`, `append_byte`, `append_u64`, `append_i64`, `append_bool`, and `append` grow it, and `clear` empties it. `s.len` and `s.len()` are the byte length. `as_str` is the `str` view; `List[u8]` has the same method, and its `push_str(text)` appends the bytes of a `str` in one copy. Where a `string` is expected (a parameter that is not `lend`, a field, a `return`, a declared variable, `List[string].push`), a `str` converts by itself: its bytes are copied into a new `string`. The other direction is written: `s.as_str()`. `a + b` builds a new `string` when one side is a `str` or a `string` and the other is a `str`, a `string`, a number, a `bool`, or a type with `to_string`. `s[a..b]` is the `str` of the bytes from `a` up to `b`; `s[a..]`, `s[..b]`, and `s[a..=b]` work too. On a `string` it is a view like `as_str`. The bounds are checked, and a bound inside a multi-byte UTF-8 character stops the program.

Text has methods, written in Greengold in the Core library; a `string` has them through its `str` view. `is_empty()`, `starts_with(p)`, `ends_with(p)`, `contains(t)`, and `eq_ignore_case(t)` return `bool`. `find(t)` and `rfind(t)` return the byte position of the first or last match as `Optional[usize]`, and `count(t)` the number of matches that do not overlap. `trim()`, `trim_start()`, `trim_end()`, `strip_prefix(p)`, and `strip_suffix(p)` return a `str` view of part of the text; `split(sep)`, `split_whitespace()`, and `lines()` return a `List[str]` of views (`lines` drops a `\r` before each `\n`). `to_upper()`, `to_lower()` (ASCII letters), `repeat(n)`, and `replace(from, to)` build a new `string`. `parse_int()` returns `Optional[i64]` and `parse_float()` returns `Optional[f64]`; both ignore spaces around the number. `xs.join(sep)` on a list builds a `string` of its elements shown as `print` shows them, with `sep` between them. Text is bytes, and these read it as UTF-8: `char_count()` counts code points, `chars()` returns them as `List[u32]`, `char_at(i)` decodes the one that starts at byte `i` and `char_len_at(i)` says how many bytes it takes, and `is_utf8()` says whether every byte belongs to a valid sequence; a byte that does not counts as one character, U+FFFD. `s.push_char(cp)` appends a code point to a `string`. `impl str:` adds methods to `str` in a program; a name the Core library already uses is an error.

```gg
fn main():
    xs = List[i32]()
    xs.push(4)
    print(xs.len, xs[0])
    b = Box[i32](9)
    print(b.value)
    owned = string.from("hi")
    print(owned)
    buf = string.new()
    buf.append_str("go")
    print(buf.len(), buf.as_str())
```

A fixed array is `[N]T` or `Array[T, N]`. A literal is `[1, 2, 3]` or `[value; count]`. `.len` is the constant length. An array may hold heap-owning elements (`[3]string`); then the array is moved, not copied, its elements are freed with it, and an element is a place like a list element: it can be read, changed, and replaced (the old one is freed), but not moved out (take a copy with `.clone()`). `[value; count]` repeats a copied value only; a moved value would end up in several places. Indexing is bounds-checked in debug and in `--release`. `--unchecked` removes those checks.

A slice `[]T` is a pointer plus a length: a view of the elements of an array, a `List`, or another slice. `xs[a..b]`, `xs[a..]`, and `xs[..b]` make one; the bounds are checked. A slice can be a parameter, a variable, a field, or a result, and it follows the rules of views (section 11): it holds the variable it was made from while it is used, so that variable cannot change, move, or go away first. A slice stored in a variable or a field is read-only; to change elements, pass a `lend []T` parameter. A slice of a temporary value is rejected unless it is an argument. An array is passed to a slice parameter without a copy of the elements. A slice of heap-owning elements (`[]string`) works the same way: an element is read in place, changed through a `lend []string`, and never moved out. An array literal passed to a slice parameter takes the slice's element type (`count(["a", "b"])` to a `[]string` makes two `string` values), and the temporary is freed after the call.

```gg
fn sum(xs: []i32) -> i32:
    total = 0
    for x in xs:
        total += x
    return total

fn main():
    print(sum([1, 2, 3]))
```

`soa Array[T, N]` lays an array of structs out as one array per field. `trust place[i]` skips the bounds check. It is legal only in `unsafe:`. A `hot fn` is an ordinary function the compiler treats as a hot path; it does not change types and does not allow `trust`.

```gg
struct Point:
    x: f32

hot fn first(xs: read [2]i32) -> i32:
    unsafe:
        return trust xs[0]

fn main():
    ps = soa Array[Point, 1]
    ps[0].x = 1.0
    print(ps[0].x, first([4, 5]))
```

## 11. References

A `str` or a slice is a view. A view made from a heap-owning variable (`s.as_str()`, a slice of a list) borrows that variable like a stored `read`, and so does a value that holds such a view (`List[str]`, a struct with a `str` field, the result of a call that was given the view). While the view is still used, the variable cannot be changed, moved, or reassigned, and the view cannot be kept in a variable of an outer scope, put in a container that outlives the variable, or returned when the variable is a local. Copying the bytes (`buf.append_str(s.as_str())`) keeps no view. String literals are static and borrow nothing.

`r: read T = place` or `r = read place` stores a shared borrow. `r: lend T = place` or `r = lend place` stores an exclusive borrow; the place cannot be `fixed`. A reference variable can be retied to another place (`r = other`) unless it is `fixed`. The borrow is tied to the variable it came from. Moving that variable, assigning it, or lending it while the stored reference is still used is an error. A reference cannot outlive the value. A reference is not consumed.

`-> ref T` and `-> lend T` return such a pointer. Every `return` must be a place inside one `read` or `lend` parameter. A call that returns `lend T` is a place: it can be assigned to (`g.value() = 5`, `g.value() += 1`) and receive a mutating method (`g.value().push(x)`). A value whose struct has a reference field, returned by a call, may point at any `read` or `lend` argument of that call, so it is tied to them. When more than one parameter could be the origin, write `-> ref T tied to name`. A field that stores a reference is `name: read T tied to self` or `name: lend T tied to self`. The `tied to` name is required. The field is not a keyword `ref`.

```gg
struct Player:
    hp: i32

fn hp_of(p: read Player) -> ref i32:
    return p.hp

fn main():
    hero = Player{ hp: 3 }
    view = read hero
    print(view.hp, hp_of(hero))
    slot: lend Player = hero
    slot.hp = 8
    print(hero.hp)
```

```gg
struct Player:
    hp: i32

struct Slot:
    who: read Player tied to self

fn pick(a: read Player, b: read Player) -> ref Player tied to b:
    return b

fn main():
    hero = Player{ hp: 2 }
    s = Slot{ who: hero }
    ally = Player{ hp: 6 }
    print(s.who.hp, pick(hero, ally).hp)
```

## 12. Numbers

`+`, `-`, and `*` on integers trap when the result does not fit. Division by zero traps. A shift whose amount is negative, or greater than or equal to the bit width, traps. The shift amount is an integer; an unsuffixed amount is `i32`. All of these checks, and the bounds checks, stay on in `--release`. Floats do not trap.

Floating-point arithmetic is IEEE 754 with the rounding of each operation as written: the compiler sets no fast-math flag and never fuses a multiply and an add on its own (the vector `fma` is the explicit form). The basic operations and `sqrt` therefore give the same bits on every IEEE machine. The functions of `std.math` call the platform's C library and may differ in the last bit between libraries; use `std.dmath` when a result must be identical everywhere (replays, lock-step simulation, ledgers). On `i386` targets the x87 unit may keep extra precision in registers, so results can differ from SSE2 machines; build with `--features +sse2` for deterministic floats there.

`overflow: wrap` makes `+`, `-`, and `*` wrap. Write it as the first statement of the function, or between the result type and the body's colon: `fn f(a: u8) -> u8 overflow: wrap:`. A `wrapping:` block does the same for the statements inside it. `overflow: trap` restores the trap. `wrapping_add`, `wrapping_sub`, and `wrapping_mul` wrap. `checked_add`, `checked_sub`, and `checked_mul` return `Optional`. `saturating_add`, `saturating_sub`, and `saturating_mul` clamp. Each of those nine names is also an infix operator: `a wrapping_add b`. `add_overflows(a, b)`, `sub_overflows(a, b)`, and `mul_overflows(a, b)` return `bool` and do not trap. Both arguments are the same integer type. The call does not write a type argument. `max_value[T]()` and `min_value[T]()` are the bounds of an integer type.

`T in lo..hi` is a bounded integer. `hi` is exclusive, so `int in 0..256` holds `0` through `255`. The word `int` in that position is `i64`. A literal outside the range is a compile error. A value of that type may index an array of length `hi - lo` without a runtime check.

```gg
fn add(a: u8, b: u8) -> u8 overflow: wrap:
    return a + b

fn main():
    n: int in 0..256 = 100
    print(i64(n))
    print(wrapping_add[u8](250, 10))
    print(checked_add[i32](1, 2).value_or(0))
    w: u8 = 250
    wrapping:
        w = w + 10
    print(add(250, 10), w, add_overflows(w, u8(10)))
```

Casts are `T(expr)` between numeric types. A conversion that keeps every value happens by itself: a smaller integer into a wider one of the same signedness (`i32` to `i64`), an unsigned integer into a wider signed one (`u8` to `i32`), `i64` and `isize`, `u64` and `usize`, `f32` to `f64`, and an integer into a float that holds it exactly (`i32` to `f64`, `u16` to `f32`). It applies to declarations, assignments, `return`, fields, arguments that are not `lend`, and both sides of an operator, where the narrower side converts: `a + b` with an `i64` and an `i32` is an `i64`. Any other mix (`i64` to `i32`, `i32` to `usize`, `i64` to `f64`) is an error whose fix writes `T(...)`. `==` and `!=` also compare structs, enums, tuples, arrays, slices, lists, `Box`, `Shared`, `Arc`, and `string`: field by field, element by element, or variant and payload, using a part's own `eq` where it has one. A function, an OS handle, a union, or a `dyn` value inside stops that, unless the type defines `eq`. `hash(x)` returns a `u64` for the same types and mixes the parts the same way, except that a float has no hash, so a type with a float needs its own `hash`. Equal values have equal hashes. Comparisons do not chain: write `a < b and b < c`. `<`, `<=`, `>`, and `>=` order numbers and text: `str` and `string` compare byte by byte, and a text that is the start of a longer one comes first (`"ab" < "abc"`), so UTF-8 text sorts by code point. `and`, `or`, and `not` are the boolean operators. Bitwise `&`, `|`, `^`, `~`, `<<`, and `>>` apply to integers. `&`, `|`, and `^` bind tighter than comparisons, as in Python: `bits & 1 == 0` is `(bits & 1) == 0`.

```gg
fn main():
    print(i64(3) + 1, not false, 1 < 2 and 2 < 3)
```

```gg
fn twice(n: i64) -> i64:
    return n * 2

fn main():
    big: i64 = 10
    small: i32 = 3
    ratio: f64 = small
    print(big + small, twice(small), ratio)
```

A SIMD vector holds a fixed number of lanes of one number type, and an operator works on every lane in one step: `f32x4`, `f32x8`, `f64x2`, `f64x4`, `i32x4`, `i32x8`, `i64x2`, `i64x4`, `i16x8`, `u8x16`, `u32x4`, `i8x16`, `i8x32`, `u8x32`. `f32x4(a, b, c, d)` gives each lane, `f32x4.splat(x)` puts `x` in every lane, and `f32x4.load(xs, i)` reads lanes `i` to `i + 4` of a slice; `v.store(xs, i)` writes them back to a `lend []f32`. Both check the bounds. `+ - * /` on float vectors and `+ - * & | ^` on integer vectors work lane by lane; integer lanes wrap and do not trap. Both sides have the same vector type. `v.lane(i)`, `v.with_lane(i, x)`, `v.sum()`, `v.min(w)`, `v.max(w)`, and `v.sqrt()` (float) are methods. `a.fma(b, c)` (float) is `a * b + c` with one rounding. `v.shr(k)` and `v.shl(k)` shift every lane of an integer vector (arithmetic for signed lanes; `k` must be below the lane's bit count or the program stops), `u8x16.as_i8()` / `i8x16.as_u8()` (also the `x32` forms) keep the bits and change the signedness, `i32x4.to_f32()` and `i32x8.to_f32()` convert to floats, `v.floor()` and `v.abs()` on float vectors, `f32x4.to_i32()` / `f32x8.to_i32()` (truncating) and the bit casts `as_i32()` / `as_f32()` between 32-bit float and integer vectors, and `a.join(b)` on `u8x16` / `i8x16` makes the 32-lane vector of `a` followed by `b`. `acc.dot_u4i8(x, w)` is the fast form of `dot_u8i8` for 4-bit data: every lane of `x` must be at most 128 (a nibble, 0..15), and lane `j` of the result gets the products of bytes `4j` to `4j+3` (`pmaddubsw` + `pmaddwd` on x86 with SSSE3). `acc.dot_i8(x, w)` and `acc.dot_u8i8(x, w)` are the multiply-add step of a quantized matrix product: on an `i32x4` (`i8x16` arguments) or an `i32x8` (`i8x32` arguments, `u8x16`/`u8x32` for the left side of `dot_u8i8`), lane `j` of the result is `acc[j]` plus the products, computed in 32 bits, of the elements `2j`, `2j+1`, `2n+2j` and `2n+2j+1` (`n` is the number of lanes of `acc`). Only the sum of all lanes is a dot product of the two vectors, and that sum is the same on every CPU. A vector is copied and prints as its lanes. `gg build --cpu native` (or `--cpu <name>` and `--features +avx2,+fma`; `GG_CPU` and `GG_FEATURES` in the environment) makes code for that CPU instead of the baseline of the target, which turns these into AVX2 and FMA instructions; the program then runs only on CPUs that have them.

```gg
fn scale(xs: lend []f32, k: f32):
    kv = f32x4.splat(k)
    i: usize = 0
    while i + 4 <= xs.len:
        (f32x4.load(xs, i) * kv).store(xs, i)
        i += 4

fn main():
    xs: [4]f32 = [1.0, 2.0, 3.0, 4.0]
    scale(xs, 2.0)
    v = f32x4(1.0, 2.0, 3.0, 4.0)
    print(xs, (v + v).sum())
```

## 13. Expressions

`if cond then a elif cond2 then b else c` is a value. `else` is required. The arms have the same type. This form has no colons.

```gg
fn main():
    n = 2
    print(if n == 0 then 0 elif n == 1 then 1 else 9)
```

`match` as a value uses `=>` and one expression per arm. It must be the last thing on its line.

```gg
fn main():
    n = Valid(2)
    x = match n:
        Valid(v) => v
        None => 0
    print(x)
```

`(a, b)` is a tuple of two to six elements, sugar for `Tuple2` ... `Tuple6`. The type is `(A, B)`. Fields are `.0`, `.1`, and so on. `a, b = expr` splits a tuple. `_` skips an element. `fixed a, b = expr` makes every new name `fixed`. `type Name = T` is a top-level alias and is substituted while parsing.

```gg
type Pair = (i32, i32)

fn both(a: i32, b: i32) -> Pair:
    return (a, b)

fn main():
    q, r = both(7, 2)
    print(q, r)
    a, _, c = (1, 2, 3)
    a += 1
    print(a, c)
```

`fn(params) -> T => expr` is a lambda. Without captured variables it is a value of type `fn(A) -> R`. A function used as a value cannot have a `read`, `lend`, or `consume` parameter. Call it like any other function.

A lambda inside a generic function or a method of a generic type may use its type parameters (`xs.count(fn(x: T) -> bool => x > limit)`); each instance of the function has its own copy of the lambda. A lambda that names a variable of the enclosing function is a closure. A copyable variable is copied into the closure when the lambda is evaluated; a heap-owning variable is borrowed as `read`, so it cannot be changed or moved while the closure is still used. When the body changes a captured variable (`fn(x: i32) => out.push(x)`), the closure borrows it as `lend`: the variable cannot be `fixed`, and nothing else may use it while the closure is still used. A closure can be called, and passed to a parameter of type `fn(A) -> R` (also of a generic function or a method): the callee is compiled for that closure, so the call is direct.

`Fn(A) -> R` is an owned closure value: it can be returned, stored in variables, fields, and lists, and called like a function. A lambda written where a `Fn` is expected (a `Fn` parameter, a `return` in a function returning `Fn`, `f: Fn(...) = ...`) owns its captures: heap values are moved in and everything else is copied, and it cannot change them. A closure value that only copies its captures, and any plain function, also converts to `Fn`. The captures live on the heap with a reference count: `f.clone()` shares them, and the last owner frees them. A call result can be called directly: `make_adder(5)(1)`, `handlers[i](x)`. A `Fn` value cannot be passed where a plain `fn(A) -> R` pointer is expected (for example to `extern` code).

```gg
fn make_adder(k: i32) -> Fn(i32) -> i32:
    return fn(x: i32) -> i32 => x + k

fn main():
    steps = List[Fn(i32) -> i32]()
    steps.push(make_adder(1))
    steps.push(make_adder(10))
    v = 0
    for i in 0..steps.len:
        v = steps[i](v)
    print(v, make_adder(5)(1))
```

```gg
fn apply(f: fn(i32) -> i32, n: i32) -> i32:
    return f(n)

fn main():
    f = fn(x: i32) -> i32 => x + 1
    print(f(2), apply(f, 4))
    k = 10
    add_k = fn(x: i32) -> i32 => x + k
    print(add_k(1), apply(add_k, 5), apply(fn(x: i32) -> i32 => x * k, 3))
```

`for x in it:` walks an iterator when the type has `next(self: lend T) -> Optional[U]`. The loop stops on `None`.

```gg
struct Count:
    cur: i32
    end: i32

impl Count:
    fn next(self: lend Self) -> Optional[i32]:
        if self.cur >= self.end:
            return None
        v = self.cur
        self.cur += 1
        return Valid(v)

fn main():
    c = Count{ cur: 0, end: 3 }
    for x in c:
        print(x)
```

## 14. Constants and compile-time functions

`const name = expr` or `const name: T = expr` is a compile-time value. Its value is built from literals (numbers, `bool`, `str`, arrays, and struct literals), earlier constants, arithmetic, bitwise operators, and casts. `comptime fn` is evaluated while compiling, and the result is a constant. It may compute numbers, arrays, structs, and enums (`Valid(3)`, `Shape.Circle(1.5)`), and use `match` with literal, range, variant, and guarded arms. It may not do I/O or allocate. A constant may also be an enum value directly: `const START = Color.Red`.

The name of a top-level function that is not generic and not a method is also a constant value (the function's address, of type `fn(...)`), so `const HANDLERS: [2]fn() = [reset, tick]` and structs of function pointers are tables the linker fills in; with `@section(".isr_vector") @used static` (or a `const`) it builds an interrupt vector table.

`static name: T = expr` is one global variable with a constant initial value, for state that outlives every call (a counter, a lookup table, the state of a device driver). Its type is plain data: numbers, `bool`, pointers, arrays, and structs of them. Every read and write of a `static`, including `addr_mut(name)`, is inside `unsafe:`, because another thread may use it at the same time.

```gg
static CALLS: i64 = 0

fn count():
    unsafe:
        CALLS += 1

fn main():
    count()
    count()
    unsafe:
        print(CALLS)
```

```gg
const STEP = 2

comptime fn sq(n: i32) -> i32:
    return n * n

fn main():
    print(sq(STEP))
```

## 15. Foreign functions and pointers

`extern "header.h" fn name(params) -> T` declares a C function. Parameters are numbers, `bool`, `str` (passed as a temporary C string), function pointers, raw pointers, `read` or `lend` of a C-compatible struct (a pointer), or a C-compatible struct by value. `consume`, slices, arrays, and heap types are not parameters. The result is a number, `bool`, a pointer, a C-compatible struct, or nothing. A struct is C-compatible when its fields are numbers, `bool`, pointers, function pointers, and C-compatible structs or arrays of them (no `union`, `packed`, or `align(N)`). A struct passed or returned by value follows the target's C calling convention, as a C compiler would: on Windows x64 a struct of 1, 2, 4, or 8 bytes travels as an integer and others through a copy; on x86-64 Linux and macOS a struct up to 16 bytes travels in integer and floating-point registers and a larger one on the stack; on arm64 a struct of up to four floats or doubles of one type travels in floating-point registers, others up to 16 bytes in integer registers, larger ones through a copy. Other targets reject a struct by value. `extern struct` is a C layout: numbers, `bool`, pointers, function pointers, nested extern structs and unions, and arrays of those.

`*T` is a read-only pointer. `*mut T` is mutable. `*void` is an untyped pointer and cannot be dereferenced. Pointers are copied and are not freed by Greengold. The pointed-to type is a number, `bool`, a struct that does not own heap memory, `void`, or another pointer.

Safe code may pass, store, and compare pointers with `null`. These need an `unsafe:` block: `p[i]`, `addr(place)`, `addr_mut(place)`, `ptr_cast[*T](p)`, `ptr_offset(p, n)`, `ptr_to_int(p)`, `int_to_ptr[*T](n)`, `cstr_to_string(p)`, `string_to_cstr(s)`, `str_from_raw(p, len)`, `slice_from_raw[T](p, len)` (a `[]T` view of `len` values at `p`; the memory must outlive the view and be aligned for `T`), `ptr_read[T](p)`, `ptr_write[T](p, value)`, `volatile_read[T](p)`, `volatile_write[T](p, value)`, the atomic intrinsics, and any call of an extern that takes or returns a pointer or is variadic. `ptr_read` moves a `T` of any type, heap owners included, out of raw memory (the memory is then uninitialized), and `ptr_write` moves one in without dropping what was there; `p` must be `*mut` for `ptr_write`. `addr` of a value that owns heap memory is a `*u8` to its bytes. `size_of[T]()` and `align_of[T]()` are `usize` and need no `unsafe:`. `volatile_read` and `volatile_write` access a number, `bool`, or pointer that hardware or another device may change, such as a memory-mapped register: every one happens, in program order, and none is merged or removed.

The atomic intrinsics are indivisible operations on an integer at a pointer: `atomic_load[T](p, order)`, `atomic_store[T](p, value, order)`, `atomic_add`, `atomic_sub`, `atomic_and`, `atomic_or`, `atomic_xor`, and `atomic_swap` (each `[T](p, value, order)` and returning the value before), `atomic_cas[T](p, expected, new, order)` (stores `new` only when the value is `expected`, and returns the value it found), and `fence(order)`. `order` is a string literal: `"relaxed"`, `"acquire"`, `"release"`, `"acq_rel"`, or `"seq_cst"`. A load cannot be `"release"` or `"acq_rel"`, and a store cannot be `"acquire"` or `"acq_rel"`. `std.thread.Atomic[T]` wraps them safely.

`asm[T]("template", "constraints", args...)` inside `unsafe:` runs inline machine code, written in LLVM's inline-assembly syntax for the target (`$0`, `$1` name the operands). The constraints list the output first when there is a result (`"=r,r"`), then one input per argument; `~{memory}` says the code touches memory. Without `[T]` there is no result. Arguments and the result are numbers, `bool`, or pointers. The code always runs; it is never removed or moved past another side effect. `ptr_offset` counts elements, and `n` is an `isize`. `ptr_to_int` returns `usize`. `str_from_raw` is not NUL-terminated. Inside `unsafe:` the compiler does not check that the pointer is live, aligned, or in bounds. `addr(place)` does not borrow `place`.

```gg
extern "stdio.h" fn printf(fmt: str, ...) -> i32 as c_printf
extern struct CPoint:
    x: i32
    y: i32

fn main():
    n: i32 = 5
    p: *CPoint = null
    unsafe:
        q = addr(n)
        print(ptr_to_int(q) == 0, p == null)
```

## 16. Imports and the library

Each file is a module. `import std.math` loads `greengold/std/math.gg` and binds the name `math` in that file only. The call is `math.sqrt(4.0)`. An import is not re-exported: a file sees only the modules it imports itself. `import "types.gg"` binds `types`. `import combat` binds `combat`. Two imports in one file cannot share a local name; write `as` to rename one. `import std.math { sqrt, sin }` brings those public names in unqualified. The three forms do not combine.

A file starts public. A line that is only `private` makes every declaration below it private. A line that is only `public` makes them public again. That covers functions, structs, enums, features, constants, externs, fields, and methods. The prelude (`Optional`, `Result`, `string`, the tuple structs, and `wrapping_*` / `checked_*` / `saturating_*`) and the builtins (`print`, `panic`, `List`, `Box`) stay unqualified in every module. `fn main` is allowed only in the file you compile. A top-level value is a `const`, or a `static` (section 14). `extern "math.h" fn sqrt(x: f64) -> f64 as c_sqrt` keeps the C symbol `sqrt` and the Greengold name `c_sqrt`. `weak extern ...` declares a C function that may be missing on other platforms: there it is null and must not be called. `target_os()` (`"windows"`, `"linux"`, `"macos"`, or `"none"`) and `target_arch()` (`"x86_64"`, `"aarch64"`, ...) are the platform being compiled for, as constant `str` values. An `if` or `elif` whose condition only compares them with string literals (joined with `and`, `or`, `not`) is decided while compiling: the branches for other platforms produce no code, so they may call `weak extern` functions that exist only there.

`gg api` prints every public symbol of the library (the core prelude is listed too). `gg api --json` prints the same catalog as JSON: `module`, `name`, `kind`, `signature`, `description`, `no_std`. The text form marks each module with `[no_std: yes|alloc|no]`: `yes` needs neither libc nor an allocator, `alloc` needs an `allocator` line (it uses `List`, `string`, ...) but not libc, `no` calls libc or the operating system, directly or through an import (a static reading of the source, checked by compiling each `yes` and `alloc` module with `--no-std`). The module field stays `std.math`; the name is `sqrt`. Names that start with `_` are omitted. Read a signature from that catalog instead of guessing a mode.

The modules are:

- `builtin`: `print`, `eprint`, `panic`, `input`, `List`, `Box`, `str`, overflow tests, pointer intrinsics, and the bounds `Num`, `Int`, `Float`, `Ord`, `Eq`. `eprint` takes the same arguments as `print` and writes them to the standard error stream.
- `core`: prelude enums, `string`, tuples, wrapping, checked, and saturating arithmetic.
- `std.bits`: `popcount`, `leading_zeros`, `trailing_zeros`, `rotate_left`/`rotate_right`, `swap_bytes`, `reverse_bits`, `ilog2`, `next_power_of_two`, bit fields (`bits_extract`, `bits_insert`), for every integer type, with no libc.
- `std.heapless`: `FixedVec`, `FixedString`, `RingBuffer`, `FixedMap`, `FixedBitSet`, `SpscRing` (a lock-free queue for one producer and one consumer), `MpmcRing` (a lock-free bounded queue for any number of both): capacity fixed at compile time, no allocation, usable with `--no-std`.
- `std.fixedpoint`: `Fx[S]` fixed-point numbers (a 64-bit integer holding the value times 2^S): exact `add`/`sub`, `mul`/`div` rounded toward zero, `saturating_*`, `sqrt`, `floor_int`/`round_int`/`trunc_int`, `format(digits)`; overflow traps. No libc.
- `std.bigint`: `BigInt`, integers of any size (`bigint_parse`, `bigint_from_i64`, `add`, `sub`, `mul`, `div_rem`, `modulo`, `pow`, `pow_mod`, `gcd`, `mod_inverse`, `shl`/`shr`, `to_string`/`to_hex`, big-endian bytes). Not constant time.
- `std.decimal`: `Decimal`, exact base-10 numbers for money (a 128-bit mantissa and a scale of 0 to 28): `decimal_parse`, `add`, `sub`, `mul`, `div(other, places, mode)`, `round(places, mode)` with the rules `HALF_EVEN`, `HALF_UP`, `HALF_DOWN`, `UP`, `DOWN`, `FLOOR`, `CEILING`.
- `std.encoding`: `hex_encode`/`hex_decode`, `base64_encode`/`base64url_encode`/`base64_decode`, `base32_encode`/`base32_decode`, and the checksums `crc32`, `crc32c`, `crc16_modbus`, `crc16_ccitt`, `crc8`, `adler32`, `fletcher16`.
- `std.hash`: `sha256`, `sha384`, `sha512` (and streaming `Sha256`/`Sha512`), `sha1`, `sha3_256`/`sha3_384`/`sha3_512`, `shake128`/`shake256`, `hmac_*`, `hkdf_sha256`, `pbkdf2_sha256`/`pbkdf2_sha512`. Portable code with no libc.
- `std.crypto`: `chacha20poly1305_seal`/`_open`, `aes_gcm_seal`/`_open` (128, 192, 256-bit keys), `x25519`, `ed25519_public_key`/`ed25519_sign`/`ed25519_verify`, `constant_time_eq`, `zeroize`, `SecretBytes` (secret bytes wiped when the value goes out of scope), `random_bytes`. Not FIPS-validated; see the header of the module for what it does and does not promise.
- `std.mmio`: `Reg[T]` (`reg8`/`reg16`/`reg32`/`reg64`): volatile reads and writes of a hardware register, `set_bits`, `clear_bits`, `modify`, bit `Field`s, `wait_bits_set` with a time limit. Safe to call; the address is the one unsafe fact, taken once.
- `std.hal`: the features that drivers share (`OutputPin`, `InputPin`, `I2c`, `SpiBus`, `Uart`, `Delay`), so a driver written once as a generic function runs on any board that implements them.
- `std.dmath`: `exp`, `ln`, `log2`, `log10`, `sin`, `cos`, `tan`, `asin`, `acos`, `atan`, `atan2`, `sinh`, `cosh`, `tanh`, `pow`, `cbrt`, `hypot` that give the same bits on every IEEE 754 machine (only `+ - * /`, `sqrt` and bit moves; within a few units in the last place of the C library).
- `std.unicode`: UTF-8 encode/decode, `to_upper`/`to_lower` (and the Turkish `_tr` forms), character classes, display `width`, simplified `grapheme_count`.
- `std.log`: leveled messages on standard error (`debug`, `info`, `warn`, `error`, `kv`), text or JSON lines, `GG_LOG` sets the start level.
- `std.uuid`: RFC 9562 `v4`, `v5`, `v7`, `parse`, `format`.
- `std.csv`: RFC 4180 `parse`, `parse_lenient`, `format_row`, any one-byte separator.
- `std.toml`: TOML 1.0 `parse` into the `std.json` tree, and `to_text`.
- `std.compress`: DEFLATE, zlib and gzip (`inflate`, `deflate`, `zlib_compress`/`zlib_decompress`, `gzip_compress`/`gzip_decompress`); every decompression call takes `max_out`, the output limit, so a small hostile file cannot fill the memory.
- `std.audit`: `AuditLog` (`open`, `open_keyed`, `append`, `head`, `len`) writes an append-only log whose entries are chained by SHA-256 (or HMAC-SHA-256), each entry put on the disk before `append` returns; `verify`, `verify_keyed`, `verify_anchored(path, count, head)` find edited, removed or swapped entries (keep `head()` outside the file to also catch a cut-off tail).
- `std.fix`: FIX messages: `parse` checks BeginString, BodyLength and CheckSum and the field syntax (`get`, `get_all`, `get_i64`); `FixBuilder` writes a message with 9 and 10 filled in. No session layer, no raw-data fields with SOH bytes.
- `std.can`: `CanFrame` (classic and CAN FD data and remote frames, 11- and 29-bit identifiers, length checks), the `CanBus` feature for controller drivers, `dlc_for_length`/`length_for_dlc`, `frame_crc15` (the CRC of classic CAN), and SAE J1939 identifiers (`j1939_id`, `j1939_parse`). No allocation.
- `std.money`: `Money` (an `i64` count of minor units, an ISO 4217 code, the currency's decimal places): `usd`/`eur`/`gbp`/`jpy`/`money_new`, `parse_money`, `plus`/`minus`/`compare` (an error for different currencies), `times`, `scaled(numerator, denominator, mode)` with explicit rounding, `allocate(ratios)` (shares that add up to exactly the amount), `to_string`.
- `std.math`: the C99 libm wrappers (f64, and `_f32` variants), `isqrt` (integer only), `is_nan`, `hypot`, plus generic `min`, `max`, `clamp`, `abs`, `signum`. Call them as `math.sqrt`.
- `std.string`: search, split, and parse helpers on `str` and `string`.
- `std.collections`: hash map (`hashmap_new[K, V]()`), hash set (`hashset_new[K]()`), and an arena. Keys and values may own heap memory (`HashMap[string, List[i32]]`). `insert` takes the key and value, `remove` returns `Optional[V]`, `get` returns a copy (`clone`), and `get_ref` a `ref V` (it stops the program when the key is missing). A key is hashed with the built-in `hash(key) -> u64` and compared with `==`: integers, `bool`, text, and structs, enums, tuples, and lists of them work as they are (no floats); a type may define its own `fn hash(self: Self) -> u64` and `fn eq(self: Self, other: Self) -> bool`. Inside generic code, the methods of a type argument are visible even when its module keeps them private. `m.entry(key, fallback)` returns the value for `key` as a `lend V`, inserting `fallback` first when the key is missing, so `counts.entry(word, 0) += 1` looks the key up once. `Deque[T].new()` is a ring buffer: `push_back`, `push_front`, `pop_front`, `pop_back` (both `Optional[T]`), `get(i)` (a `ref T`), `at(i)` (a `lend T`), `len`, `to_list`. `heap_min[T: Ord]()` and `heap_max[T: Ord]()` are binary heaps: `push`, `pop` (`Optional[T]`, the smallest or the largest), `peek`. `priority_queue[P: Ord, V]()` orders values of any type by a priority, smallest first: `push(priority, value)`, `pop`, `peek_priority`. `sorted_map[K: Ord, V]()` keeps its keys in order: `insert`, `get`, `get_or`, `entry`, `remove`, `contains`, `first_key`, `last_key`, `floor(k)` (the largest key `<= k`), `ceiling(k)` (the smallest key `>= k`), `keys_between(lo, hi)` (`lo <= k < hi`), `keys`, `values`. A lookup is a binary search; `insert` and `remove` shift the later entries. Also `SortedSet` (`sorted_set[K]()`) and `BitSet` (`bitset_new()`, with `union_with`, `intersect_with`, `subtract`).
- `std.sort`: `sort` and `sort_by` on `lend List[T]`, and `binary_search`. `sort_stable` and `sort_stable_by` keep equal elements in order (merge sort, one extra buffer); `is_sorted`.
- `std.fs`: every operation that can fail has a `Result[T, io.IoError]` form: `read_text`, `write_text`, `append_text`, `write_atomic`, `copy_file`, `delete_file`, `replace_file`, `create_dir`, `create_dir_all`, `remove_dir`, `remove_dir_all`, `read_dir` (sorted `DirEntry` list), `walk`, `metadata` (size, kind, modification time), `current_dir`, `set_current_dir`, `absolute_path`, `temp_dir`; and the older `Optional`/`bool` forms `read_file_to_string`, `write_string_to_file`, `file_exists`, `remove_file`, `make_dir`, `is_dir`, `list_dir`, `rename_file`, plus `path_join`, `path_parent`, `path_name`, `path_ext`. Directories use the system's own calls (no shell).
- `std.intern`: `intern_new` and `Intern.put`, `Intern.text`, `Intern.len`. Each distinct byte string is stored once at a stable address. The id is a `usize`.
- `std.process`: `process_exit`, `env_get`, `host_is_windows`, `args`, `process_run`. `args` returns the process arguments as `List[str]`, with the program name at index 0. `process_run` takes a `read List[str]` and returns `Optional[ProcessResult]` (`code`, `out`, `err`). `process_run_input(argv, input)` does the same with `input` as the program's standard input. `spawn_read(argv)` and `spawn_write(argv)` (`argv` is a `[]str`) start a program and return an `io.File` that streams its standard output or feeds its standard input; `f.wait()` closes the stream, waits for the program, and returns its exit code (a program ended by a signal gives 128 plus the signal on POSIX).
- `std.time`: `current_time`, `clock_ticks`, `unix_millis` (also `current_time_millis`), `monotonic_nanos`, `sleep_millis`, and `Instant.now()` with `elapsed_nanos`, `elapsed_millis`, `elapsed_secs`. `DateTime` is a UTC date and time (`year`, `month`, `day`, `hour`, `minute`, `second`, `millis`): `now_utc()`, `datetime_from_unix_millis(ms)`, `to_unix_millis`, `weekday` (0 is Monday), `add_millis`, `to_iso` (`2026-10-11T08:30:00Z`), and `parse_iso(text) -> Result[DateTime, string]`, which reads a date, an optional time and fraction, and `Z` or a `+HH:MM` offset. `is_leap_year` and `days_in_month` help with calendars. Also `Duration` (`duration_millis`, `describe`, arithmetic), `DateTime` calendar arithmetic (`add_days`, `add_months`, `add_business_days`, `day_of_year`, `start_of_day`) and `format`/`parse_format` patterns (`YYYY-MM-DD HH:mm:ss.SSS`), time zones with daylight saving (`zone_by_name("America/New_York")`, `Zone.to_local`, `Zone.from_local`; today's rules for about 45 zones), and leap seconds with TAI and GPS time (`tai_minus_utc`, `unix_to_gps_millis`, `gps_week_and_seconds`).
- `std.io`: `File` streams: `File.open(path)`, `File.create(path)`, `File.append(path)` return `Result[File, IoError]`; `write(text)`, `write_line(text)`, `read_some(max)`, `read_rest()`, `read_exact(n)`, `read_line() -> Result[Optional[string], IoError]`, `flush()`, `sync_all()` (fsync), `seek(offset)`, `size()`, `position()`. A file is flushed and closed when it goes away. `IoError` has a `kind` (`NotFound`, `PermissionDenied`, `AlreadyExists`, ...), the system's `code`, and a `message` that names the path. The features `Reader` and `Writer` let one function take a `File`, one of `stdin()`/`stdout()`/`stderr()`, or an in-memory `Cursor` (`cursor_new(text)`).
- `std.net`: TCP and UDP over IPv4, with time limits, TLS, and many sockets at once. `TcpListener.bind(host, port)` (port 0 picks a free one; `port()` says which), `accept()`, `accept_timeout(ms)` and `try_accept()` (`Optional[TcpStream]`; `None` when nobody came); `TcpStream.connect(host, port)`, `connect_timeout(host, port, ms)`, `connect_tls(host, port, ms)`, `send(text)`, `receive(max)` (an empty result means the other side closed), `receive_all()`, `receive_exact(n)`, `send_frame(data)` / `receive_frame(max_len)` (a 4-byte big endian length, then the bytes), `try_receive(max)` (`None` when nothing has come), `send_some(data)`, `readable(ms)`, `peer_addr()`, `set_timeout(ms)`, `set_nodelay(on)`, `set_nonblocking(on)`, `set_buffers(r, s)`, and `handle()`. Hosts are dotted IPv4 addresses, `"localhost"`, or a name the system looks up. `set_timeout(ms)` limits every later send and receive: a call that waits longer returns `Err("timed out")` (`net.is_timeout(e)` tests for it) and the stream stays usable; a negative time removes the limit. TCP sockets are made with `TCP_NODELAY` on, and a closed connection is an `Err`, not a signal. `Poller.new()` waits for many sockets at once: `add(handle, also_write)`, `remove(handle)`, and `wait(ms)` returns a `PollEvent` (`handle`, `readable`, `writable`, `error`) for each socket that is ready; with `try_accept`, `try_receive`, and `receive_from_try` one thread serves thousands of connections (see `std.packet`). `UdpSocket.bind(host, port)` sends and receives single datagrams: `send_to(data, host, port)`, `reply(datagram, data)`, `receive_from(max)` (limited by `set_timeout`), `receive_from_try(max)`, `set_broadcast(on)`, and `set_buffers(r, s)`; `receive_from` returns a `Datagram` (`data`, `host`, `port`); a datagram longer than `max` is cut (on Windows it is an error). A socket is closed when it goes away.
- `std.http`: HTTP/1.1 over `std.net`. `parse_request(text)` and `read_request(stream, max_bytes)` return a `Request` (`method`, `path`, `query`, `version`, `headers`, `body`, with `header(name)` and `query_param(key)`). `response(status, body)` makes a `Response`; `set_header`, `header`, and `to_text()` write it with `Content-Length`. `serve(listener, app, limit)` answers requests one at a time with `app.handle(req)` for any type that has `fn handle(self: read Self, req: read Request) -> Response` (the `Handler` feature), and stops after `limit` requests (never when negative); a client that is silent for 10 seconds is dropped, and `serve_with(listener, app, limit, timeout_ms)` sets that time. The client is for `http://` and `https://` URLs: `get(url)`, `get_timeout(url, ms)`, `request(method, url, body)`, and `fetch(method, url, body, opts)` with `opts = http.options()` (`timeout_ms`, 30 seconds by default, applies to the connect, the TLS handshake, and every receive; `max_redirects`, 5 by default, 0 returns the 3xx response itself; `max_body`; `opts.header(name, value)`). It follows redirects and reads a body sent with `Content-Length`, `Transfer-Encoding: chunked` (`decode_chunked`), or until the server closes. `https` checks the certificate against the system's trusted roots and the host name; a bad certificate is an `Err`, never accepted quietly. `parse_response`, `url_encode`, `url_decode`, and `status_text` help.
- `std.tls`: TLS for clients, under `TcpStream.connect_tls` and `https`. On Windows it uses the system's SChannel; on Linux and macOS it uses OpenSSL 1.1.1 or 3 (`libssl`; the linker is given `-lssl -lcrypto` when a program uses TLS, so install `libssl-dev`, `openssl-devel`, or `brew install openssl`). There is no TLS server yet.
- `std.sock`: `wait(fd, writable, ms)` and `poll_many(fds, want, ms)`, waiting for sockets with a time limit; `std.net` and `std.tls` are built on them.
- `std.packet`: binary messages for game and server protocols. `ByteWriter.new()` with `put_u8`, `put_bool`, `put_u16`, `put_u32`, `put_u64`, `put_i16`, `put_i32`, `put_i64`, `put_f32`, `put_f64` (little endian; `put_u16_be`, `put_u32_be`, `put_u64_be` for network order), `put_bytes`, `put_str` (2-byte length), and `as_str()`. `ByteReader.new(data)` with the matching `get_*`, each returning `Result` (a short packet is an `Err`, never a crash), and `remaining()`. `FrameBuffer.new()` takes whatever bytes arrived with `push(data)` and gives whole length-prefixed messages with `next(max_len)` (`None` when more bytes are needed; an error when the announced length is above `max_len`); `frame(data)` writes one.
- `std.json`: JSON whose shape is not known ahead, as a tree: `Json` is `Null`, `Bool`, `Num` (`f64`), `Str`, `Arr` (`List[Json]`), or `Obj` (`List[Member]`, each a `key` and a `value`, in text order). `parse(text) -> Result[Json, string]` reports what is wrong and at which byte. `get(key)` and `at(i)` return a copy, or `Null` when it is missing, so lookups chain (`doc.get("user").get("name")`); `has`, `len`, `keys`, `is_null`, `as_f64`, `as_i64`, `as_bool`, `as_string` (each `Optional`), `as_f64_or`, and `as_str_or` read values. `object()`, `array()`, and `text(s)` start values; `set(key, value)` and `push(value)` change them. `to_text()` writes compact JSON and `to_pretty()` indents it; `to_json(x)` writes a `Json` field as it is.
- `std.regex`: regular expressions matched in time linear in the text. `compile(pattern) -> Result[Regex, string]`; `is_match`, `find` and `find_from(text, start)` (`Optional[Match]`), `find_all`, `replace_all(text, with)` (`$1` is a group's text, `$$` a dollar), `split`, and `group_count`. A `Match` has `start` and `end` (byte positions), `text()`, `group(i)` (`Optional[string]`, group 0 is the whole match), `group_start(i)`, and `group_end(i)`. The syntax is literals, `.`, `[...]` and `[^...]` with ranges, `\d \w \s \D \W \S`, `^`, `$`, ``, `\B`, `(...)`, `(?:...)`, `|`, and `* + ? {n} {n,} {n,m}`, each made lazy by a following `?`. Characters are UTF-8 code points; the leftmost match wins, and among matches that start there, the one the pattern prefers.
- `std.rand`: `Rng`, seeded with `rng_new`; it is fast and repeatable but not for secrets. `secure_bytes(n)` and `secure_u64()` read the operating system's cryptographic random source, and `rng_from_entropy()` seeds an `Rng` from it.
- `std.tasks`: tasks that take turns on one thread, for programs that wait on many things at once. `async fn f(params) -> T:` declares a function whose call starts its body as a task and returns a `Task[T]` at once (a function without a result gives a `Task[bool]`); the arguments move into the task, so a parameter cannot be `read` or `lend` (GG0328) and must be able to go to another thread (GG0326), and a method cannot be `async` (GG0134). `await t` waits for the task and returns its result; it consumes `t`. Using `async` or `await` imports `std.tasks` by itself. `tasks.spawn(fn() -> T => ...)` starts any lambda as a task, `sleep(ms)` and `yield_now()` let the other tasks run, and `wait_readable(fd)` / `wait_writable(fd)` wait for a socket; `TcpListener.accept_async`, `TcpStream.receive_async`, and `UdpSocket.receive_from_async` in `std.net` use them. Tasks switch only where one waits, so no lock is needed between them. Each task has its own stack (a fiber on Windows, a `ucontext` on Linux and macOS), so any function called from a task may wait, not only an `async fn`. The program itself is a task: `await` in `main` runs the other tasks until the result is there. A `Task` that goes away without `await` is waited for there. Sockets are waited for with `poll` (`WSAPoll` on Windows). Tasks belong to the first thread that uses them: a call from any other thread stops the program ("tasks belong to one thread"), because the scheduler is shared by the whole program.
- `std.thread`: `Thread`, `Mutex`, `Cond`, `Atomic[T: Int]` (lock-free: `load`, `store`, `fetch_add`, `fetch_sub`, `swap`, `compare_exchange`), `AtomicI64`, `ChannelI64` (of `i64`), `Channel[T]` (bounded or unbounded, any `T`, with `recv_timeout`), `Queue[T]`, `Semaphore`, `Barrier`, `RwLock`, `Once`, `ThreadLocal`, `Mutex.try_lock`, `Cond.wait_timeout`, and `Locked[T]`. This is a pthread wrapper. `Thread.spawn(f)` runs a `fn()` or a lambda on a new thread; the lambda's captures move into the thread. `Queue[T]` is a blocking queue of owned values: `send(v)` moves `v` in, `recv()` waits and returns `Optional[T]` (`None` once `close()` was called and the queue is empty). `Locked[T]` keeps a value behind its own mutex: `m.lock()` waits for the mutex and returns a `Guard[T]`, `g.value()` is the value itself (`lend T`, so `g.value() += 1` and `g.value().push(x)` change it), and the mutex opens when the guard goes away. The guard holds a reference to the `Locked`, so it cannot outlive it, cannot go to another thread, and the `Locked` cannot move while it is used; a second `lock()` on the same thread while a guard lives waits forever. `get()` returns a copy (`clone`), and `set(v)` and `replace(v)` store a new value, each under the lock. The eight types are OS handles: they are moved like a heap value and never copied, so `n = m` moves `m` instead of making a second, unrelated lock. `clone()` and `copy` of a handle, or of a value that holds one, are rejected (GG0323). Their methods take `read self` (except `join`), so one handle can be shared by several threads through `Arc`. `t.join()` joins once; a second `join` panics.
- `std.parallel`: `Pool.new(threads)` starts a pool of worker threads (`threads` counts the caller; 0 means one per CPU, `cpu_count()`), `size()` says how many take part, and `for_range(n, f, ctx)` calls `f(start, end, ctx)` for pieces of `0..n` on all of them and returns when every piece is done (`for_range_chunked(n, chunk, f, ctx)` fixes the piece size). `f` is a `fn(usize, usize, *u8)` and `ctx` a raw pointer to what it needs, usually a struct on the caller's stack that holds slices and a `*mut` output pointer; the pieces never overlap, so each may write the part of the output that belongs to its range. The workers sleep between calls and are joined when the pool goes away. The compiler does not check what a piece does with `ctx`, so a piece must not write anywhere outside its own range. Ready-made jobs: `map_i64`/`map_f64(pool, src, dst, f)` and `reduce_i64`/`reduce_f64(pool, src, init, op)`; `reduce_*` folds fixed pieces of `REDUCE_CHUNK` (4096) items and combines them left to right, so the answer is the same on any number of threads, even for float addition. (`for_range_chunked` hands out the same pieces on a one-thread pool.)
- `std.mmap`: `MappedFile.open(path)` maps a file for reading (`Result[MappedFile, string]`); `len()` is its size and `bytes()` a `[]u8` view of the whole file, valid until the `MappedFile` goes away. Nothing is read until the bytes are used, so a file of several gigabytes opens at once.

A parameter written `p: send T` hands its argument to another thread. There is no `Send` or `Share` bound to write: the compiler infers from the type whether a value may cross. It may not when it holds a view (`str`, a slice, a reference field), a raw pointer, a `Shared` (its count is not atomic), or a stored `Fn` value (its captures are unknown); a lambda written at the call is checked capture by capture. `Arc[T]` crosses when `T` does, and a `std.thread` handle when what it carries does. The error is GG0326 and names the capture and the reason.

```gg
import std.thread { Thread, Queue }

fn main():
    q = Arc[Queue[string]](Queue[string].new())
    mine = q.clone()
    worker = Thread.spawn(fn() => drain(mine))
    q.value.send("one")
    q.value.send("two")
    q.value.close()
    worker.join()

fn drain(q: Arc[Queue[string]]):
    while let Valid(job) = q.value.recv():
        print(job)
```

```gg
import std.math

fn main():
    print(math.sqrt(4.0))
```

```gg
import std.math as numbers

fn main():
    print(numbers.sqrt(4.0))
```

```gg
import std.math { sqrt }

fn main():
    print(sqrt(4.0))
```

A `public` line and a `private` line stand alone. Declarations under `public` are visible to other files. The file starts public.

```gg
fn answer() -> i32:
    return 7

private

fn hidden() -> i32:
    return 0

fn main():
    print(answer(), hidden())
```

### Passing a value, arrays, and input

A bare parameter of a move type that the body only reads is a borrow, so the caller keeps the value.

```gg
fn length(xs: List[i32]) -> usize:
    return xs.len

fn main():
    xs = List[i32]()
    xs.push(1)
    print(length(xs), xs.len)
```

`p: T` on a copyable struct copies. `p: read T` borrows. After either call the caller still has the value. Only `consume`, or storing a move-type place, takes it away.

```gg
struct Pair:
    a: i32
    b: i32

fn see(p: Pair):
    print(p.a)

fn peek(p: read Pair):
    print(p.b)

fn main():
    p = Pair{ a: 1, b: 2 }
    see(p)
    peek(p)
    print(p.a)
```

An array may repeat one value. The count is a constant.

```gg
fn main():
    xs: [3]i32 = [0; 3]
    print(xs[0], xs.len)
```

When the body of `for x in xs:` changes `x` (assigns it, or calls a method that changes it), `x` lends each element of the array or list, so the change writes the element. The loop must go over a variable or a field that is not `fixed`. Otherwise `x` is a read-only copy or `read` reference. A loop counter (`for i in 0..n:`, `for i in n:`) and a byte of a `str` cannot be changed.

```gg
fn main():
    xs: [2]i32 = [1, 2]
    for x in xs:
        x = x + 10
    print(xs[0])
```

`input()` reads a line as `str`. A prompt is a `str`. `panic` takes one `str` or `string`, such as `panic(f"bad index: {i}")`, and does not return to the caller. `print` and `{x}` in an f-string show numbers, `bool`, and text as they are. A struct shows as `Point { x: 1, y: 2 }`; a list, an array, or a slice as `[1, 2, 3]`; an enum as `Shape.Circle(1.5)`; the prelude enums as `Valid(3)`, `None`, `Ok(1)`, and `Err("e")`. Text inside them is quoted. A type with `fn to_string(self) -> string` shows through it. Pointers, functions, and thread handles do not print. Printing only reads the value. `x.to_string()` returns that text as a `string` for any type `print` shows. `to_json(x)` returns the JSON text of a value, generated for its type: a struct is an object of its fields, a list, an array, a slice, and a tuple are arrays, `Optional` is the value or `null`, an enum variant without a payload is its name as a string and one with a payload `{"Name": value}` (several values in an array), `Box`, `Shared`, and `Arc` are their value, and text is escaped. A float that is not finite is `null`. A type with `fn to_json(self) -> string` writes through it. `from_json[T](text)` returns `Result[T, string]`: it reads the form `to_json` writes, skips keys it does not know, fills a missing `Optional` field with `None`, and otherwise reports what is wrong and at which byte (a missing field, a number that does not fit, a duplicate key). `T` must own its data: `string` rather than `str`, `List[T]` rather than a slice, and no pointers, functions, handles, or `Shared` values.

```gg
fn main():
    print(input())
```

```gg
struct Point:
    x: i32
    y: i32

fn main():
    text = to_json(Point{ x: 1, y: 2 })
    print(text)
    match from_json[Point](text.as_str()):
        Ok(p): print(p.x + p.y)
        Err(e): print(e)
    print(from_json[Point]("{\"x\": 1}"))
```

## 17. Widths, precedence, and rejected forms

Integer ranges are the usual two's-complement bounds. `isize` and `usize` are 64-bit on the supported hosts.

| Type | Smallest | Largest |
|---|---|---|
| `i8` | -128 | 127 |
| `i16` | -32768 | 32767 |
| `i32` | -2147483648 | 2147483647 |
| `i64`, `isize` | -9223372036854775808 | 9223372036854775807 |
| `u8` | 0 | 255 |
| `u16` | 0 | 65535 |
| `u32` | 0 | 4294967295 |
| `u64`, `usize` | 0 | 18446744073709551615 |

A literal that does not fit its type is a compile error. An unsuffixed integer defaults to `i32` when nothing forces another integer type. An unsuffixed float defaults to `f64`.

Operators, from loosest to tightest: `or`; `and`; `not`; `== != < <= > >=`; `|`; `^`; `&`; `<< >>`; `+ -`; `* / %`; unary `- ~`; then calls, fields, indexes, and `?`. Comparison does not chain. `&` is tighter than `==`, so `bits & 1 == 0` is the mask test `(bits & 1) == 0`.

Update operators are `= += -= *= /= %= &= |= ^= <<= >>=`. They need a mutable place. `/` and `%` on integers are truncating division and remainder. They do not produce a float.

Escapes in strings and characters are `\n \t \r \\ \' \"`. `\0` is legal in a character and not in a string. A character holds one byte. A string may span lines inside `"""`. `f"..."` and `$"..."` interpolate; both are a `string`.

```gg
fn main():
    print("""ab""")
    print('A', '\n')
```

These are rejected. The diagnostic names the rule; do not invent a nearby syntax.

- `else if`. The keyword is `elif`. `elif` after `if let` is the same rejection.
- Syntax from other languages: `&&`, `||`, `!x`, `x++`, `x--`, a `;` between or after statements, `let x = ...`, and `def`/`func`/`function` for `fn`. Each is reported (GG0133) with a `safe` fix: `and`, `or`, `not x`, `x += 1`, a new line, `x = ...`, and `fn`.
- A reference field with no `tied to` name.
- `//` as a comment. The comment character is `#`.
- A tab used for indentation.
- `consume x` as an expression, including at a call. Ownership is the parameter mode, or the move of a heap place.
- `fn Type.method`. Methods go in `impl Type:`.
- A second function, type, field, or local with the same name. There is no overloading.
- A missing `fn main():` in an executable.
- An `if` value with no `else`, or a `match` that skips a variant and has no `_`.
- `?` inside an argument, a condition, or the right-hand side of `+=`.
- A slice of a temporary value outside an argument, a write through a slice stored in a variable or a field, and a slice as a type argument or an enum payload.
- `consume` of a number, `bool`, `str`, or array of numbers.
- Using a name after it was passed to a `consume` parameter, or after it was moved into another owner.
- Lending a `fixed` variable, or assigning to one.
- Passing two `lend` arguments that overlap, or a `lend` together with a `read` or `consume` of the same place.
- A numeric conversion that can lose information (`i64` to `i32`, `i32` to `usize`, `i64` to `f64`), and `string` where a `str` is expected. Write `i32(n)` or `s.as_str()`.
- An extern that takes `consume`, a slice, an array, or a heap type.
- Pointer indexing or `addr` outside `unsafe:`.
- Moving a heap element out of a `List` (`x = v[i]` in a `List[List[T]]` or `List[string]`). The element can be read and changed in place; take a copy with `v[i].clone()` or take it out with `pop`.
- `[value; count]` with a value that is moved, not copied, and a count above 1.
- A `dyn Feature` made from a type that holds a view, or a call through it of a method that takes `self` as `consume`, mentions `Self` in another position, takes a moved value, or returns a reference.
- `Send`, `Share`, or a lifetime name. A reference is `read`, `lend`, or `tied to`.

`self` follows the same modes as any parameter. `self` alone is a copy when the type is copyable; when the type owns heap memory its mode is inferred like any parameter (`read`, `lend`, or `consume`). `self: lend Self` mutates. `self: read Self` borrows. `self: consume Self` takes the value: `x.into_parts()` moves `x`.

A generic is instantiated only when something uses it. A body that uses more than its bounds promise is reported where it is declared; an error that depends on the concrete type (a move of a `T` that is a `List`) is reported at the use, with the concrete type arguments. A function call infers its type arguments from its arguments: `id(7)`. Write them when nothing else gives them: `List[i32]()`, `Optional[i32].None` when nothing else shows what `None` holds, and a generic struct literal whose fields do not show every type parameter.

`gg check file.gg --json` is the repair loop. Each diagnostic has `code`, `rule`, `message`, `span`, `labels`, and `fixes`. `labels` name the definition, the consume, and the later use. `details.callee` and `details.parameter` name the signature that caused a move. Apply a fix only when `applicability` is `safe` or `likely` and `verified` is true. `verified` means the compiler applied that edit to a copy and the diagnostic went away without a new one. A `safe` fix is the only sensible repair (`&&` to `and`, a missing `:`, `import std.math` for `sqrt`); a `likely` fix is a guess that compiles (a misspelled name, a `T(...)` conversion, the missing `match` arms). A `manual` fix is a hint, not an edit. `gg fix` applies them.

## 18. What the tools check

`gg check file.gg` type-checks and prints diagnostics. It does not generate code. A syntax error does not stop the check: the broken line is skipped and the rest of the file is still checked, so one run lists every mistake; errors that only follow from the skipped line are hidden as cascades. `gg fix [paths]` applies every verified `safe` fix and repeats until none is left; `--likely` also applies verified `likely` fixes, and `--dry-run` only prints them. The language server offers each fix as a quick fix, and `source.fixAll.greengold` applies the `safe` ones, so an editor can repair a file on save (the VS Code extension turns this on). `gg check file.gg --json` writes the same diagnostics as JSON. `gg attrs file.gg` writes the `@attribute` uses as JSON (section 4). `gg check --profile safety` also holds the program to a coding profile: no `unsafe`, `panic`, recursion, heap use, unbounded loops or mutable statics, and bounded complexity (`--max-complexity`, `--max-statements`); `--allow RULE` switches a rule off, an `@allow` attribute grants a reviewed exception, and `--list-allowed` lists them. `gg coverage` summarizes data written by `gg run --coverage` or `gg test --coverage`: statement, decision, condition and MC/DC coverage (`--annotate` lists what never ran, `--lcov FILE` writes an LCOV file). `gg fuzz file.gg` runs `fn fuzz_target(data: []u8)` on mutated inputs guided by coverage, saves a shrunk input for each crash (`--crashes`), and replays one with `--replay`. `gg sbom` prints a software bill of materials (CycloneDX or SPDX). `gg repro` builds twice in different directories and compares the bytes. `gg unsafe-audit` lists every `unsafe` block, inline assembly, foreign function, custom allocator and static. `gg explain GG0301` explains one code. `gg fmt` rewrites a file into one layout: four spaces for each block, `else` and `elif` level with `if`, no trailing spaces. `gg fmt --check` exits 1 when a file is not that layout. Formatting the result again changes nothing. An indent that has only one legal repair is a `safe` fix on the diagnostic. `gg test` runs every `fn test_*():` and every `test` block. A panic or a failed `require` fails that one test. `gg test --json` writes the same report as JSON: `summary.passed`, `summary.failed`, and one object per test with `name`, `file`, `line`, `kind` (`function` or `block`), `status` (`passed` or `failed`), and `message`. `gg build` and `gg run` compile. `-g` adds debug information (DWARF): a debugger stops at `.gg` lines, shows them in stack traces, and prints locals by name: numbers, `bool`, structs, enums (the variant, then its values), fixed arrays, `str`, slices, `List`, `Box`, `Shared`, and `Arc`. `gg debug-scripts` prints how to load the printers that ship with the compiler into gdb or lldb; with them a `string` or `str` prints as its text, a `List` or slice as its elements, a `HashMap` as its keys and values, and an enum value as `Valid(7)`. `--release` optimizes and still checks bounds and integer overflow. `--unchecked` removes bounds checks. `--forbid-heap`, `--forbid-recursion`, and `--max-stack BYTES` check the generated code and fail the build when code reachable from an entry point can allocate, when the call graph has a cycle, or when the deepest call chain (locals of every function plus 32 bytes per call) may use more stack than the limit; calls through function pointers, closures and `dyn` values are not followed, and `gg stack-usage` prints the table (`--json` for a tool). `--linker-script FILE` links with that script. `--no-std` omits libc; `panic` becomes a trap, and `print` is unavailable. `--target NAME` compiles for another machine: any LLVM triple, or a short name (`linux-x64`, `linux-arm64`, `linux-riscv64`, `macos-x64`, `macos-arm64`, `windows-x64`, `windows-arm64`, `wasm32`, `wasm32-wasi`, `cortex-m0`, `cortex-m3`, `cortex-m4`, `cortex-m7`, `cortex-m33`, `riscv32`); `gg targets` lists them and whether this machine can link for them. Linking for another machine uses `<triple>-gcc`, `$GG_LINKER`, clang with `ld.lld` (with a C library from `GG_SYSROOT`, or none for `--no-std`), or `zig cc`; without one, `gg build` writes the object file and prints how to link it. On the host, `gg build` links with `$CC`, gcc, cc, or clang, and otherwise with `zig cc`, which carries the C libraries of every target: zig is `$GG_ZIG`, the `ziglang` Python package, or `zig` on `PATH`, and `GG_LINKER=zig` prefers it. `gg toolchain` prints the LLVM version, the linker, zig, and the debuggers it found. `wasm32` is always freestanding: the result is a `.wasm` module that exports `_start`, and its `extern` functions are imports the host supplies. `wasm32-wasi` has a C library (wasi-libc): `print`, `input`, the heap, and `List` work, and the module imports the WASI calls from the host. It links when `$GG_WASI_SYSROOT` names a wasi-libc sysroot and `wasm-ld` is installed (the browser playground ships its own). `std.thread`, `std.tasks`, and `std.net` are not available there, and `usize` stays 64 bits wide.

`gg new name` writes `gg.toml` and `src/main.gg`. `--template` picks `bin`, `lib`, `cli`, or `cortex-m` (a bare-metal Cortex-M4 project with `link.ld`). `gg.toml` has `[package]` (`name`, `version`, `edition`, `main`, and `repository` for publishing) and `[dependencies]`. The edition defaults to the latest one this compiler knows; an unknown edition is an error. A dependency is an import root, so `import lib.util` binds `util`. It is `lib = { path = "..." }`, `lib = { git = "URL", tag = "v1.2.0" }` (or `branch`, or `rev` with a commit), or a version from the registry, `lib = "1.2"`: the newest published version from 1.2.0 below 2.0.0 (below 1.0, `"0.3"` means 0.3.x), or `"=1.2.4"` exactly. The registry is an index directory or git repository of `NAME.toml` files, named by `[registry] index = "..."` or the `GG_REGISTRY` environment variable. Dependencies of dependencies are resolved the same way, and one name resolves to one source. `gg fetch` downloads them into `~/.greengold/packages` and writes `gg.lock`, which pins each git dependency to a commit; `gg build` does the same when needed, and later builds keep the locked commits until `gg update --deps` (plain `gg update` updates the compiler itself). `gg publish --index DIR` adds the package's version at its current commit to an index. With no file on the command line, `gg build` and `gg run` compile `main`.

Parameter modes are inferred from bodies, so a library records its public API instead of writing every mode. `gg api --lock` writes `gg.api.lock`: each public function with the type and the inferred mode of every parameter, each public struct, enum, feature, and constant, and whether a type is copied or moved. `gg api --check` compares the package with the lock and exits 1 on a breaking change the version in `gg.toml` does not allow; `gg build` prints the same as warnings. A breaking change needs a new major version (a new minor one below 1.0): a removed or retyped symbol, a parameter that asks more of the caller (`read` to `lend` or `consume`, `lend` to `consume`), a new field in a struct whose fields are all public, a new enum variant, a type that becomes moved. A new symbol and a parameter that asks less (`consume` or `lend` to `read`) are compatible. A content hash in `.gg-cache/` skips a rebuild when the sources are unchanged. `gg emit-ll` writes LLVM IR. `gg emit-bc` writes bitcode. `gg doc` writes Markdown from the `#` comment above each declaration. `gg bindgen` writes `extern` declarations from a C header: functions, `#define` and `enum` constants, each named C enum as an enum with numbered variants, structs as `extern struct`, unions as `union`, function pointers as `fn(...)` types, and consecutive bitfields as one integer field per storage unit with a comment that names the bits. What it cannot translate is listed as `# skipped:` lines. `gg bindgen --cpp header.hpp` binds a C++ header: it writes `<name>_shim.cpp` (C entry points that call the C++ code) and `<name>.gg`, where each C++ class is a struct owning one object (`Type.new(...)` constructs it, `const` methods take `read self`, others `lend self`, and `drop` deletes it) and each function a function; `std::string` and `const char*` are `str` in and `string` out. A package compiles C and C++ files listed in gg.toml under `[native] sources` (with optional `flags` and `libs`) and links them, the C++ runtime included. `gg lsp` speaks the language server protocol.

A diagnostic has a stable `GGxxxx` code. Fix the code the message names. Do not invent a second syntax to satisfy an error: if the diagnostic says a parameter is `consume`, the call stays `f(x)` and the signature is what changes, or the use after the move is what goes away.
