# Chapter 03: Functions, Methods, and Lambdas

Functions are the basic building blocks that split a code base into logical pieces and make it reusable. Besides classic procedural functions, Greengold supports object-oriented methods, static constructors, first-class function pointers, and lightweight lambdas.

---

## 1. Function Declaration

A function is declared with the `fn` keyword. Parameter types are given with `:`; the return type, if there is one, is shown with `->`:

```gg
# A pure function that adds two numbers and returns an i32
fn add(a: i32, b: i32) -> i32:
    return a + b

# A function that returns no value (void)
fn log_message(msg: str):
    print("[LOG]:", msg)

fn main():
    result = add(15, 27)
    log_message("Addition finished")
    print("Result:", result)
```

### Rules:
1. If a function does not specify `-> Type`, its return type is `void`.
2. Every function with `-> Type` must contain a valid `return` statement on all code paths.

---

## 2. Methods and `impl` Blocks

Greengold has **`struct`** and **`enum`** types instead of classes (`class`). In keeping with Greengold's philosophy that *"there should be one obvious way to do something"*, the only way to add methods to data types is **`impl`** blocks.

```gg
struct Rectangle:
    width: f64
    height: f64

impl Rectangle:
    # A method reaches the object's fields through the self parameter:
    fn area(self) -> f64:
        return self.width * self.height

fn main():
    rect = Rectangle{ width: 10.0, height: 5.0 }
    print("Area:", rect.area())
```

> **Note:** Method definitions outside a block, written directly as `fn Rectangle.area(...)`, are not supported; the compiler always points you to the matching `impl` block.

### 2.1 The `self` Parameter and Mutability
When a method defined inside an `impl` block writes a bare `self`, its type is taken to be the enclosing type (`Self`) automatically:

```gg
struct Player:
    name: str
    health: i32

impl Player:
    # The type of the `self` parameter is inferred as `Player`:
    fn is_alive(self) -> bool:
        return self.health > 0

    # A method that changes the object in place (lend mode):
    fn take_damage(self: lend Player, amount: i32):
        self.health -= amount
        if self.health < 0:
            self.health = 0

fn main():
    hero = Player{ name: "Aragorn", health: 100 }
    hero.take_damage(35)
    print("Health left:", hero.health)
    print("Alive?:", hero.is_alive())
```

### 2.2 Static Methods (Constructors)
Methods whose first parameter is not `self` become **static methods** of the type. They are usually used as object constructors (factories):

```gg
struct Vector2:
    x: f64
    y: f64

impl Vector2:
    # A static constructor that takes no self:
    fn zero() -> Vector2:
        return Vector2{ x: 0.0, y: 0.0 }

    fn new(x: f64, y: f64) -> Vector2:
        return Vector2{ x: x, y: y }

fn main():
    v1 = Vector2.zero()
    v2 = Vector2.new(3.5, 4.2)
    print("v1:", v1.x, v1.y)
    print("v2:", v2.x, v2.y)
```

---

## 3. Function Pointers

In Greengold, functions are first-class citizens. You can store functions in variables, pass them as parameters, or assign them to a struct field.

### 3.1 Function Type Syntax: `fn(T1, T2) -> Ret`

```gg
# A type alias for functions that take two i32 and return an i32:
type MathOp = fn(i32, i32) -> i32

fn multiply(a: i32, b: i32) -> i32:
    return a * b

fn apply_op(op: MathOp, x: i32, y: i32) -> i32:
    return op(x, y)

fn main():
    current_op: MathOp = multiply
    print("Result:", apply_op(current_op, 6, 7))  # 42
```

### 3.2 Function Pointer Inside a Struct (Callback)

```gg
struct ClickHandler:
    button_id: i32
    on_click: fn(i32)

fn notify_user(id: i32):
    print("Button pressed! Button no:", id)

fn main():
    handler = ClickHandler{ button_id: 101, on_click: notify_user }
    
    # Trigger the callback:
    handler.on_click(handler.button_id)
```

---

## 4. Anonymous Lambdas

Without defining a separate `fn`, you can write lightweight anonymous functions on a single line:

```gg
fn(parameters) [-> ReturnType] => expression
```

### 4.1 Lambdas That Return a Value

```gg
fn transform(items: [3]i32, func: fn(i32) -> i32):
    for x in items:
        print(func(x))

fn main():
    nums: [3]i32 = [1, 2, 3]
    
    # A lambda that squares:
    transform(nums, fn(x: i32) -> i32 => x * x)
    
    # A lambda that adds two numbers:
    adder = fn(a: i32, b: i32) -> i32 => a + b
    print("Sum:", adder(10, 20))
```

### 4.2 Lambdas That Return No Value
When no return type is given, the body must be a call expression directly:

```gg
fn main():
    logger = fn(s: str) => print("[LOG]:", s)
    logger("The lambda ran successfully!")
```

### 4.3 Lambdas That Capture Outer Variables (Closures)
A lambda can use the variables of the function it is written in. Copyable values (numbers, plain structs) are copied when the lambda is created; heap-owning values (`List`, `string` ...) are borrowed as `read`. As long as the closure is in use, the borrowed variable cannot be changed or moved; the compiler checks this.

```gg
fn apply(f: fn(i32) -> i32, x: i32) -> i32:
    return f(x)

fn main():
    k = 3
    add_k = fn(x: i32) -> i32 => x + k     # k was copied
    print(add_k(1), apply(add_k, 10))       # 4 13

    xs = List[i32]()
    xs.push(7)
    has = fn(i: i32) -> bool => xs.len > usize(i)   # xs was borrowed
    print(has(0))
    xs.push(8)                              # has is no longer used: free
```

### 4.4 Zero-Cost Design
The compiler lifts every lambda into a hidden file-level function (lifting). A capturing lambda becomes a hidden struct that holds the captured values. When a closure is passed to a parameter of type `fn(...)`, the called function is compiled separately for that closure; the call is direct, with no heap allocation and no call through a pointer.

If the body changes a captured variable (`fn(x: i32) => out.push(x)`), the closure borrows it as `lend`: the variable must not be `fixed`, and it cannot be reached from anywhere else while the closure is in use.

### 4.5 Closures You Can Store: `Fn(A) -> R`
To return a closure from a function, or to keep it in a struct field or a list, use the `Fn(...)` type. A lambda written where `Fn` is expected **owns** what it captures: heap values are moved into it, the others are copied. For that reason it cannot change them. `f.clone()` shares the same closure; the last owner frees the environment.

```gg
fn make_adder(k: i32) -> Fn(i32) -> i32:
    return fn(x: i32) -> i32 => x + k

fn main():
    add5 = make_adder(5)
    print(add5(1), make_adder(2)(3))    # 6 5
    steps = List[Fn(i32) -> i32]()
    steps.push(make_adder(10))
    print(steps[0](1))                   # 11
```

`fn(...)` is a plain function pointer (it can be passed to C); `Fn(...)` is an owned closure value.

---

## 5. Attributes: Labels on Functions, Structs, and Fields

An **attribute** is a label line, `@name` or `@name(args)`, written directly above a `fn`, a method inside `impl`, a `struct`, or a struct field. The compiler gives an attribute no behavior of its own: it checks the label and records it, and a tool or code generator reads it. This is how you mark things like "this function is called over the network" or "this field is saved to disk" without adding a keyword to the language.

Unlike decorators in some other languages, an attribute does **not** wrap or change the function at run time. It is information only.

### 5.1 Declare First, Then Use

An attribute must be declared before it is used, so a misspelled name is an error and not a silent no-op:

```text
attribute name(param: kind, param: kind = default) on fn, struct, field
```

* A `kind` is `str`, `int`, `float`, `bool`, or `ident` (a bare name such as `server`).
* `= value` makes a parameter optional.
* `on fn, struct, field` limits where the attribute may be written. Leave it out to allow it anywhere.
* Arguments are positional or `key=value`, and are literals or bare names, never expressions.
* The same attribute may be written only once on an item.

### 5.2 A Small Example

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

Output:
```text
7
```

The program runs exactly as if the attribute lines were not there. A mistake is caught at compile time:

```text
Error: Unknown attribute `@replcated`.
  = help: Did you mean `@replicated`?
```

### 5.3 Reading Attributes from a Tool

`gg attrs file.gg` type-checks the program and prints every labeled function, struct, and field as JSON: its name, owner, file and line, parameter types and modes, and each attribute with its arguments filled in (defaults included):

```json
{ "kind": "fn", "name": "hit", "owner": "Player",
  "attrs": [{ "name": "replicated", "args": { "mode": "server", "reliable": true } }],
  "params": [{ "name": "self", "type": "Player", "mode": "lend" },
             { "name": "amount", "type": "i32", "mode": "" }] }
```

A script can read this list and generate code from it: network stubs, a save-game table, an editor property list. A game engine written in Greengold would build its `replicated` support this way.

---

## 6. Practice: A Mathematical Filter and Transformer

Let's design a functional example that brings together what we have learned:

```gg
# pipeline.gg
type Predicate = fn(i32) -> bool
type Mapper = fn(i32) -> i32

struct Pipeline:
    filter_func: Predicate
    map_func: Mapper

impl Pipeline:
    fn run(self, data: [5]i32):
        for x in data:
            if self.filter_func(x):
                transformed = self.map_func(x)
                print("Processed:", x, "->", transformed)

fn is_even(n: i32) -> bool:
    return n % 2 == 0

fn main():
    pipe = Pipeline{
        filter_func: is_even,
        map_func: fn(n: i32) -> i32 => n * 10
    }
    
    numbers: [5]i32 = [1, 2, 3, 4, 5]
    print("Pipeline that multiplies even numbers by 10:")
    pipe.run(numbers)
```

Output:
```text
Pipeline that multiplies even numbers by 10:
Processed: 2 -> 20
Processed: 4 -> 40
```

---

## 🎯 Chapter Summary and Exercises

In this chapter you learned:
* Standard functions and `void` functions.
* Struct methods (`Rectangle.area`) and `impl` blocks.
* Static functions that take no `self` (`Vector2.zero()`).
* Function pointers `fn(...) -> Ret` and type aliases.
* Zero-cost lambdas `fn(x) => expr` and closures that capture outer variables.
* Attributes `@name(args)`: declared labels on functions, structs, and fields that tools read with `gg attrs`.

### Try It Yourself:
1. Define a struct named `Circle` (`radius: f64`). In an `impl Circle:` block, write both an `area()` method and a static `unit()` constructor (a circle with radius 1.0).
2. Write an `integrate`-like helper function that takes an `fn(f64) -> f64`, and test the function $x^2$ with a lambda.

You are now ready to move on to the most distinctive and vital mechanism of the language: [Chapter 04: Ownership, Modes, and Memory](04_Ownership_Modes_and_Memory.md)!
