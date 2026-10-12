# Chapter 07: Generics, Features, and Operator Overloading

The power of a programming language is measured by its ability to build abstractions that do not repeat themselves (DRY), are type-safe, and also have zero run-time cost. Greengold reaches this goal with **generics**, **structural features**, and **operator overloading**.

---

## 1. Generic Functions and Structs

Generics let you write a single algorithm or data structure that works with different data types. Type parameters are written in square brackets as `[T]`.

### 1.1 Generic Functions
Let's write a universal `max` function that returns the larger of two values:

```gg
fn max[T: Ord](a: T, b: T) -> T:
    if a > b:
        return a
    return b

fn main():
    # Automatic, through type inference:
    print(max(10, 25))          # T = i32
    print(max(3.14, 2.71))      # T = f64

    # Calling with an explicit type argument:
    print(max[i64](100, 200))
```

### 1.2 Generic Data Structures (`struct` and `enum`)

```gg
struct Pair[A, B]:
    first: A
    second: B

impl Pair[A, B]:
    fn swap(self) -> Pair[B, A]:
        return Pair[B, A]{ first: self.second.clone(), second: self.first.clone() }

fn main():
    p = Pair[i32, str]{ first: 1, second: "one" }
    swapped = p.swap()
    print(swapped.first, swapped.second)  # "one" 1
```

### 1.3 Static Resolution (Monomorphization - Zero Cost)
For every different combination of generic types (for example `Pair[i32, str]`, `Pair[f64, f64]`), the Greengold compiler produces special, optimized native code at compile time (like C++ templates). There is no extra overhead, boxing, or type erasure at run time.

---

## 2. Features (`feature`) and Structural Conformance

A **feature** is a contract that defines the abilities and method signatures a data type must have.

### 2.1 Defining a Feature
Method bodies are not written inside a feature. The **`Self`** keyword is used to stand for the data type in question:

```gg
feature Printable:
    fn to_string(self: Self) -> str

feature Measurable:
    fn area(self: Self) -> f64
```

### 2.2 There Is No Explicit `impl` Declaration! (Go-Style Structural Matching)
In Greengold, for a type to satisfy a feature you do not need to write artificial and clumsy declarations such as `impl Printable for Player`!

> **Rule:** If a `struct` or `enum` defines all the methods declared in a feature **with the same name, the same number of parameters, the same mode (`read`/`lend`), and the same return type**, it satisfies that feature **automatically**.

```gg
struct Circle:
    radius: f64

# Circle exactly satisfies the `area` method of the Measurable feature:
impl Circle:
    fn area(self) -> f64:
        return 3.14159 * self.radius * self.radius

struct BoxObject:
    side: f64

# BoxObject provides the same method too:
impl BoxObject:
    fn area(self) -> f64:
        return self.side * self.side
```

### 2.3 Feature Bounds
Features are used as bounds to restrict and guarantee the abilities of generic type parameters:

```gg
# A function that accepts only types that satisfy the `Measurable` feature:
fn print_object_area[T: Measurable](item: T):
    print("Area:", item.area())

fn main():
    c = Circle{ radius: 2.0 }
    b = BoxObject{ side: 5.0 }

    print_object_area(c)  # Valid! Circle satisfies Measurable.
    print_object_area(b)  # Valid! BoxObject satisfies Measurable.
```

### 2.4 Multiple Feature Bounds (`+`)
You can require a type to have more than one ability:

```gg
fn display_area[T: Measurable + Printable](item: T):
    print(item.to_string(), "Area:", item.area())
```

### 2.5 Built-in Feature Bounds
The compiler provides ready-made feature bounds for commonly used basic abilities:
* `Num`: Numeric types (`+`, `-`, `*`, `/`)
* `Int`: Integers only
* `Float`: Floating-point numbers only
* `Ord`: Orderable types (`<`, `>`, `<=`, `>=`)
* `Eq`: Types that can be checked for equality (`==`, `!=`)

---

## 3. Operator Overloading

Greengold v4 lets you attach mathematical and logical operators (`+`, `-`, `*`, `==`, `<`) directly to data structures you define yourself.

Greengold has no complex symbolic operator syntax. **Operators map directly to specific method names:**

| Operator | Matching method signature | Description |
|---|---|---|
| `a + b` | `fn add(self, o: Other) -> Result` | Addition |
| `a - b` | `fn sub(self, o: Other) -> Result` | Subtraction |
| `a * b` | `fn mul(self, o: Other) -> Result` | Multiplication |
| `a / b` | `fn div(self, o: Other) -> Result` | Division |
| `a % b` | `fn rem(self, o: Other) -> Result` | Remainder |
| `-a` | `fn neg(self) -> Result` | Unary minus (negation) |
| `a == b` | `fn eq(self, o: Other) -> bool` | Equality (`!=` is derived automatically) |
| `a < b` | `fn lt(self, o: Other) -> bool` | Less than (`>`, `<=`, `>=` are derived) |

### 3.1 Operator Overloading in a Vector Example

```gg
# vector2d.gg
struct Vec2:
    x: f64
    y: f64

impl Vec2:
    # The + operator:
    fn add(self, o: Vec2) -> Vec2:
        return Vec2{ x: self.x + o.x, y: self.y + o.y }

    # The - operator:
    fn sub(self, o: Vec2) -> Vec2:
        return Vec2{ x: self.x - o.x, y: self.y - o.y }

    # Unary negation (-v):
    fn neg(self) -> Vec2:
        return Vec2{ x: -self.x, y: -self.y }

    # Equality check (==):
    fn eq(self, o: Vec2) -> bool:
        return self.x == o.x and self.y == o.y

fn main():
    v1 = Vec2{ x: 3.0, y: 4.0 }
    v2 = Vec2{ x: 1.0, y: 2.0 }

    # Now we can use the standard mathematical operators!
    v3 = v1 + v2
    v4 = v1 - v2
    v_inv = -v1

    print("v3 (Sum):", v3.x, v3.y)  # 4.0 6.0
    print("v4 (Difference):", v4.x, v4.y)    # 2.0 2.0
    print("Inverse of v1:", v_inv.x, v_inv.y)# -3.0 -4.0
    print("Equal?:", v1 == v2)       # false
    print("Different?:", v1 != v2)     # true (through eq, automatically)
```

---

## 🎯 Chapter Summary and Exercises

In this chapter you learned:
* Zero-cost monomorphized generic functions and structs.
* Go-style structural features with no formalities.
* Multiple feature bounds such as `[T: Num + Ord]`.
* Operator overloading by defining methods such as `add`, `sub`, `neg`, `eq`.

### Try It Yourself:
1. Define a `Complex` (complex number) struct (`re: f64`, `im: f64`). Write the `add` and `mul` methods so that complex addition and multiplication work with the `+` and `*` operators.
2. Try writing a `bubble_sort(items: lend []T)` function with the constraint `[T: Ord]`.

Now let's move on to the most critical area of systems programming, [Chapter 08: Error Handling and the Core Library](08_Error_Handling_and_Prelude.md)!
