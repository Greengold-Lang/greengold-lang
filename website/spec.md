# Greengold

Greengold (`.gg`) is a statically typed, indentation-sensitive language compiled to machine code through LLVM. This file is the language a program must follow. One example is given for each feature. When this file and the compiler disagree, the compiler wins: `gg check --json` is the diagnostic interface, and `gg api --json` is the library interface.

There is one way to write each construct. A call does not repeat the parameter mode. `else if` is not a keyword. `own` is not a keyword. `//` is not a comment.

## 1. A program

A file is a sequence of top-level declarations: `struct`, `enum`, `feature`, `impl`, `fn`, `test`, `const`, `extern`, `import`, `type`, `comptime fn`, and `hot fn`. Other statements live inside a function. An executable has `fn main():` with no parameters and no result.

Indentation is four spaces. A tab is a syntax error. A block opens with `:` and the next line indents by exactly four. A comment starts with `#` and runs to the end of the line. One statement per line.

```gg
# The entry point. print writes its arguments and a newline.
fn main():
    print("Hello, Greengold")
```

## 2. Names, types, and literals

Names are letters, digits, and `_`. Type parameters start with an uppercase letter. Primitive types are `i8 i16 i32 i64 isize`, `u8 u16 u32 u64 usize`, `f32 f64`, `bool`, and `str`. `int` means `i32`, `uint` means `u32`, `float` means `f32`, and `double` means `f64`, except in a bounded integer (section 12), where the word `int` means `i64`.

There is no `char` type. A character literal such as `'A'` or `'\n'` has type `u8`. A string literal has type `str`, a read-only view of bytes. `true` and `false` are `bool`. Integers may use `_` separators and `0x` or `0b` prefixes. A float literal has a decimal point and defaults to `f64`.

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

An interpolated string is `f"..."` or `f"""..."""`. `{expr}` is replaced; `{{` and `}}` are braces. The result is a `str`.

```gg
fn main():
    name = "gg"
    print(f"hello {name}")
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

## 5. Copy and move

Numbers, `bool`, `str`, raw pointers, and structs and enums that do not contain `Box`, `List`, `string`, or a `std.thread` handle are copied. Copying a struct copies its fields. `consume` on a number, `bool`, or array of numbers is an error.

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

`if`, `elif`, and `else` open blocks. The condition is `bool`. The keyword is `elif`, not `else if`. `while` repeats while the condition is true. `break` and `continue` affect the innermost loop, including when they appear inside `match`. `pass` is an empty statement. `require cond` stops the program when `cond` is false. When `cond` compares two numbers, `bool` values, or `str` values (`require a == b`, `<`, `<=`, `>`, `>=`, `!=`), the message shows both sides: `require condition failed: add(2, 3) == 4 (left: 5, right: 4)`.

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

A struct names its fields and their types. A literal writes every field: `Name{ field: expr }`. Methods are declared inside `impl Name:`, not as `fn Name.method`. The first parameter is the receiver. Bare `self` means `self: Self`. A method with no receiver is called as `Type.name(...)`.

A method with the operator's name is that operator. `+` is `add`. Binary `-` is `sub`. Unary `-` is `neg` and takes no extra argument. `*` is `mul`, `/` is `div`, `%` is `rem`, `&` is `bitand`, `|` is `bitor`, and `^` is `bitxor`. `==` is `eq`. `!=` is `not` applied to `eq`. `<` is `lt`, `<=` is `le`, `>` is `gt`, and `>=` is `ge`. A comparison method returns `bool`. Defining `lt` does not define `>`. An enum takes methods in `impl Name:` the same way. A generic impl repeats the parameters: `impl Pair[A, B]:`.

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

An enum has one or more variants. A variant is `Name` or `Name(T, U)` with positional fields. Construct it as `Enum.Name` or `Enum.Name(expr)`. `Valid`, `None`, `Ok`, and `Err` are the short forms of the prelude enums. In a pattern a bare name is a variant, not a new variable. `_` ignores a payload or catches the rest. A `match` must cover every variant, or end with `_`. An arm body is a block; an empty arm is an error, so write `pass`.

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

A generic declaration lists its type parameters in brackets: `struct Pair[A, B]`, `fn id[T](x: T) -> T`. A type writes the arguments: `Pair[i32, str]`. A struct literal may leave them out when the field values show every parameter, or when the expected type gives them: `Pair{ first: 1, second: "a" }` is a `Pair[i32, str]`. A generic body is checked at each instantiation, not when it is declared.

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

A `feature` is a set of method signatures, with optional default bodies. `Self` is the implementing type. A struct or enum satisfies the feature when it has every method that has no default body, with the same arity and modes. It does not write `impl Feature for Type`. Default methods are then available; a method written on the type replaces the default. There is no dynamic dispatch.

Use a feature as a bound: `fn show[T: Describable](x: T)` or `struct Box[T: Num + Ord]`. Built-in bounds are `Num`, `Int`, `Float`, `Ord`, and `Eq`. `Eq` is numbers, `bool`, and `str`.

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

`List[T]()` is an empty owned list. `push`, `pop`, `clear`, `swap(i, j)`, `swap_remove(i)`, `remove(i)`, and `insert(i, x)` require a list that is not `fixed`. `pop` returns `Optional[T]`; `swap_remove(i)` (moves the last element into the gap) and `remove(i)` (keeps the order) return the element. Positions are bounds-checked; `insert` accepts `i == len`. `.len` is a `usize`; `.len()` is the same length, on a list, an array, a slice, a `str`, and a `string`. `xs[i]` is bounds-checked. It is a place inside the list: it can be read, changed through a list that is not `fixed` (`xs[i].push(1)`, `xs[i] = v` frees the old element), and passed as `read` or `lend`. It cannot be moved out; use `xs[i].clone()` or `pop`. `get(i)` returns `ref T`. An array cannot hold a heap element.

`Box[T](value)` owns one heap value. Read and write `.value`.

`Shared[T](value)` is a heap value with several owners. `s.clone()` adds an owner and copies no data; the value is freed when the last owner goes away. `.value` can be read but not changed or moved out, because other owners see the same value. The count is not atomic: a `Shared` value is not for passing between threads.

`string` is an owned growable buffer (`List[u8]` underneath). `str` is a view. `"..."`, indexing, and `s.len` use `str`. `string.new()` is empty. `string.from(text)` and `text.to_string()` build an owned string. On a string that is not `fixed`, `append_str`, `append_byte`, `append_u64`, `append_i64`, `append_bool`, and `append` grow it, and `clear` empties it. `s.len` and `s.len()` are the byte length. `as_str` is the `str` view; `List[u8]` has the same method. Where a `string` is expected (a parameter that is not `lend`, a field, a `return`, a declared variable, `List[string].push`), a `str` converts by itself: its bytes are copied into a new `string`. The other direction is written: `s.as_str()`. `a + b` builds a new `string` when one side is a `str` or a `string` and the other is a `str`, a `string`, a number, a `bool`, or a type with `to_string`. `s[a..b]` is the `str` of the bytes from `a` up to `b`; `s[a..]`, `s[..b]`, and `s[a..=b]` work too. On a `string` it is a view like `as_str`. The bounds are checked, and a bound inside a multi-byte UTF-8 character stops the program.

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

A fixed array is `[N]T` or `Array[T, N]`. A literal is `[1, 2, 3]` or `[value; count]`. `.len` is the constant length. Indexing is bounds-checked in debug and in `--release`. `--unchecked` removes those checks.

A slice `[]T` is a pointer plus a length. It may be a parameter and may not be stored, returned, or put in a struct. An array is passed to a slice parameter without a copy of the elements.

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

`-> ref T` and `-> lend T` return such a pointer. Every `return` must be a place inside one `read` or `lend` parameter. When more than one parameter could be the origin, write `-> ref T tied to name`. A field that stores a reference is `name: read T tied to self` or `name: lend T tied to self`. The `tied to` name is required. The field is not a keyword `ref`.

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

Casts are `T(expr)` between numeric types. A conversion that keeps every value happens by itself: a smaller integer into a wider one of the same signedness (`i32` to `i64`), an unsigned integer into a wider signed one (`u8` to `i32`), `i64` and `isize`, `u64` and `usize`, `f32` to `f64`, and an integer into a float that holds it exactly (`i32` to `f64`, `u16` to `f32`). It applies to declarations, assignments, `return`, fields, arguments that are not `lend`, and both sides of an operator, where the narrower side converts: `a + b` with an `i64` and an `i32` is an `i64`. Any other mix (`i64` to `i32`, `i32` to `usize`, `i64` to `f64`) is an error whose fix writes `T(...)`. Comparisons do not chain: write `a < b and b < c`. `and`, `or`, and `not` are the boolean operators. Bitwise `&`, `|`, `^`, `~`, `<<`, and `>>` apply to integers. `&`, `|`, and `^` bind tighter than comparisons, as in Python: `bits & 1 == 0` is `(bits & 1) == 0`.

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

A lambda that names a variable of the enclosing function is a closure. A copyable variable is copied into the closure when the lambda is evaluated; a heap-owning variable is borrowed as `read`, so it cannot be changed or moved while the closure is still used. When the body changes a captured variable (`fn(x: i32) => out.push(x)`), the closure borrows it as `lend`: the variable cannot be `fixed`, and nothing else may use it while the closure is still used. A closure can be called, and passed to a parameter of type `fn(A) -> R` (also of a generic function or a method): the callee is compiled for that closure, so the call is direct.

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

`const name = expr` or `const name: T = expr` is a compile-time value. `comptime fn` is evaluated while compiling, and the result is a constant. It may compute numbers, arrays, and structs. It may not do I/O or allocate.

```gg
const STEP = 2

comptime fn sq(n: i32) -> i32:
    return n * n

fn main():
    print(sq(STEP))
```

## 15. Foreign functions and pointers

`extern "header.h" fn name(params) -> T` declares a C function. Parameters are numbers, `bool`, `str` (passed as a temporary C string), `read` or `lend` of a C-compatible struct, or a raw pointer. `consume`, slices, arrays, and heap types are not parameters. The result is a number, `bool`, a pointer, or nothing. `extern struct` is a C layout: numbers, `bool`, pointers, nested extern structs, and arrays of those.

`*T` is a read-only pointer. `*mut T` is mutable. `*void` is an untyped pointer and cannot be dereferenced. Pointers are copied and are not freed by Greengold. The pointed-to type is a number, `bool`, a struct that does not own heap memory, `void`, or another pointer.

Safe code may pass, store, and compare pointers with `null`. These need an `unsafe:` block: `p[i]`, `addr(place)`, `addr_mut(place)`, `ptr_cast[*T](p)`, `ptr_offset(p, n)`, `ptr_to_int(p)`, `int_to_ptr[*T](n)`, `cstr_to_string(p)`, `string_to_cstr(s)`, `str_from_raw(p, len)`, and any call of an extern that takes or returns a pointer or is variadic. `ptr_offset` counts elements, and `n` is an `isize`. `ptr_to_int` returns `usize`. `str_from_raw` is not NUL-terminated. Inside `unsafe:` the compiler does not check that the pointer is live, aligned, or in bounds. `addr(place)` does not borrow `place`.

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

A file starts public. A line that is only `private` makes every declaration below it private. A line that is only `public` makes them public again. That covers functions, structs, enums, features, constants, externs, fields, and methods. The prelude (`Optional`, `Result`, `string`, the tuple structs, and `wrapping_*` / `checked_*` / `saturating_*`) and the builtins (`print`, `panic`, `List`, `Box`) stay unqualified in every module. `fn main` is allowed only in the file you compile. There are no global variables: a top-level value is a `const`. `extern "math.h" fn sqrt(x: f64) -> f64 as c_sqrt` keeps the C symbol `sqrt` and the Greengold name `c_sqrt`.

`gg api` prints every public symbol (the core prelude is listed too). `gg api --json` prints the same catalog as JSON: `module`, `name`, `kind`, `signature`, `description`. The module field stays `std.math`; the name is `sqrt`. Names that start with `_` are omitted. Read a signature from that catalog instead of guessing a mode.

The modules are:

- `builtin`: `print`, `eprint`, `panic`, `input`, `List`, `Box`, `str`, overflow tests, pointer intrinsics, and the bounds `Num`, `Int`, `Float`, `Ord`, `Eq`. `eprint` takes the same arguments as `print` and writes them to the standard error stream.
- `core`: prelude enums, `string`, tuples, wrapping, checked, and saturating arithmetic.
- `std.math`: `sqrt`, `sin`, `cos`, and the other libm wrappers, plus `abs_*`, `min_i64`, `max_i64`. Call them as `math.sqrt`.
- `std.string`: search, split, and parse helpers on `str` and `string`.
- `std.collections`: hash map (`hashmap_new[K, V]()`), hash set (`hashset_new[K]()`), and an arena. Keys and values may own heap memory (`HashMap[string, List[i32]]`). `insert` takes the key and value, `remove` returns `Optional[V]`, `get` returns a copy (`clone`), and `get_ref` a `ref V` (it stops the program when the key is missing). A key is hashed with the built-in `hash(key) -> u64` and compared with `==`: integers, `bool`, `str`, and `string` work as they are; a struct or enum key defines `fn hash(self: Self) -> u64` and `fn eq(self: Self, other: Self) -> bool`. Inside generic code, the methods of a type argument are visible even when its module keeps them private.
- `std.sort`: `sort` and `sort_by` on `lend List[T]`, and `binary_search`.
- `std.fs`: `read_file_to_string`, `write_string_to_file`, `file_exists`, `remove_file`, `path_join`, `path_parent`, `path_name`, `path_ext`, `is_dir`, `make_dir`, `list_dir`, `rename_file`.
- `std.intern`: `intern_new` and `Intern.put`, `Intern.text`, `Intern.len`. Each distinct byte string is stored once at a stable address. The id is a `usize`.
- `std.process`: `process_exit`, `env_get`, `host_is_windows`, `args`, `process_run`. `args` returns the process arguments as `List[str]`, with the program name at index 0. `process_run` takes a `read List[str]` and returns `Optional[ProcessResult]` (`code`, `out`, `err`).
- `std.time`: `current_time`, `clock_ticks`, `current_time_millis`.
- `std.rand`: `Rng`, seeded with `rng_new`.
- `std.thread`: `Thread`, `Mutex`, `Cond`, `AtomicI64`, `Channel`. This is a pthread wrapper. There is no `Send` or `Share` bound. A function passed to `Thread.spawn` cannot capture, and it cannot take `read` or `lend` parameters. The five types are OS handles: they are moved like a heap value and never copied, so `n = m` moves `m` instead of making a second, unrelated lock. `clone()` and `copy` of a handle, or of a value that holds one, are rejected (GG0323). Share a handle by passing it as `read` or `lend`. `t.join()` joins once; a second `join` panics.

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

`input()` reads a line as `str`. A prompt is a `str`. `panic` takes one `str` or `string`, such as `panic(f"bad index: {i}")`, and does not return to the caller. `print` and `{x}` in an f-string show numbers, `bool`, and text as they are. A struct shows as `Point { x: 1, y: 2 }`; a list, an array, or a slice as `[1, 2, 3]`; an enum as `Shape.Circle(1.5)`; the prelude enums as `Valid(3)`, `None`, `Ok(1)`, and `Err("e")`. Text inside them is quoted. A type with `fn to_string(self) -> string` shows through it. Pointers, functions, and thread handles do not print. Printing only reads the value.

```gg
fn main():
    print(input())
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

Escapes in strings and characters are `\n \t \r \\ \' \"`. `\0` is legal in a character and not in a string. A character holds one byte. A string may span lines inside `"""`. `f"..."` and `$"..."` interpolate; both are a `str`.

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
- Storing a `[]T`, returning a `[]T`, or putting a `[]T` in a struct.
- `consume` of a number, `bool`, `str`, or array of numbers.
- Using a name after it was passed to a `consume` parameter, or after it was moved into another owner.
- Lending a `fixed` variable, or assigning to one.
- Passing two `lend` arguments that overlap, or a `lend` together with a `read` or `consume` of the same place.
- A numeric conversion that can lose information (`i64` to `i32`, `i32` to `usize`, `i64` to `f64`), and `string` where a `str` is expected. Write `i32(n)` or `s.as_str()`.
- An extern that takes `consume`, a slice, an array, or a heap type.
- Pointer indexing or `addr` outside `unsafe:`.
- Moving a heap element out of a `List` (`x = v[i]` in a `List[List[T]]` or `List[string]`). The element can be read and changed in place; take a copy with `v[i].clone()` or take it out with `pop`.
- An array or slice whose element owns heap memory.
- A feature object or any other dynamic dispatch. Bounds are monomorphized.
- `Send`, `Share`, or a lifetime name. A reference is `read`, `lend`, or `tied to`.

`self` follows the same modes as any parameter. `self` alone is a copy when the type is copyable; when the type owns heap memory its mode is inferred like any parameter (`read`, `lend`, or `consume`). `self: lend Self` mutates. `self: read Self` borrows. `self: consume Self` takes the value: `x.into_parts()` moves `x`.

A generic is instantiated only when something uses it. An error in the body is reported at the use, with the concrete type arguments. A function call infers its type arguments from its arguments: `id(7)`. Write them when nothing else gives them: `List[i32]()`, `Optional[i32].None` when nothing else shows what `None` holds, and a generic struct literal whose fields do not show every type parameter.

`gg check file.gg --json` is the repair loop. Each diagnostic has `code`, `rule`, `message`, `span`, `labels`, and `fixes`. `labels` name the definition, the consume, and the later use. `details.callee` and `details.parameter` name the signature that caused a move. Apply a fix only when `applicability` is `safe` or `likely` and `verified` is true. `verified` means the compiler applied that edit to a copy and the diagnostic went away without a new one. A `safe` fix is the only sensible repair (`&&` to `and`, a missing `:`, `import std.math` for `sqrt`); a `likely` fix is a guess that compiles (a misspelled name, a `T(...)` conversion, the missing `match` arms). A `manual` fix is a hint, not an edit. `gg fix` applies them.

## 18. What the tools check

`gg check file.gg` type-checks and prints diagnostics. It does not generate code. A syntax error does not stop the check: the broken line is skipped and the rest of the file is still checked, so one run lists every mistake; errors that only follow from the skipped line are hidden as cascades. `gg fix [paths]` applies every verified `safe` fix and repeats until none is left; `--likely` also applies verified `likely` fixes, and `--dry-run` only prints them. The language server offers each fix as a quick fix, and `source.fixAll.greengold` applies the `safe` ones, so an editor can repair a file on save (the VS Code extension turns this on). `gg check file.gg --json` writes the same diagnostics as JSON. `gg explain GG0301` explains one code. `gg fmt` rewrites a file into one layout: four spaces for each block, `else` and `elif` level with `if`, no trailing spaces. `gg fmt --check` exits 1 when a file is not that layout. Formatting the result again changes nothing. An indent that has only one legal repair is a `safe` fix on the diagnostic. `gg test` runs every `fn test_*():` and every `test` block. A panic or a failed `require` fails that one test. `gg test --json` writes the same report as JSON: `summary.passed`, `summary.failed`, and one object per test with `name`, `file`, `line`, `kind` (`function` or `block`), `status` (`passed` or `failed`), and `message`. `gg build` and `gg run` compile. `--release` optimizes and still checks bounds and integer overflow. `--unchecked` removes bounds checks. `--no-std` omits libc; `panic` becomes a trap, and `print` is unavailable.

`gg new name` writes `gg.toml` and `src/main.gg`. `gg.toml` has `[package]` (`name`, `version`, `main`) and `[dependencies]`. A dependency `lib = { path = "..." }` is an import root, so `import lib.util` binds `util`. With no file on the command line, `gg build` and `gg run` compile `main`. A content hash in `.gg-cache/` skips a rebuild when the sources are unchanged. `gg emit-ll` writes LLVM IR. `gg emit-bc` writes bitcode. `gg doc` writes Markdown from the `#` comment above each declaration. `gg bindgen` writes `extern` declarations from a C header. `gg lsp` speaks the language server protocol.

A diagnostic has a stable `GGxxxx` code. Fix the code the message names. Do not invent a second syntax to satisfy an error: if the diagnostic says a parameter is `consume`, the call stays `f(x)` and the signature is what changes, or the use after the move is what goes away.
