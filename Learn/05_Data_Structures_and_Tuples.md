# Chapter 05: Data Structures and Tuples

The foundation of modern software development is combining related data under sensible structures. Greengold offers **`struct`**, which takes the place of classes in object-oriented languages, **`enum`**, which provides algebraic data types, **`tuple`**, which makes returning multiple values easy, and hardware-friendly **arrays/slices**.

---

## 1. Structs

A `struct` gathers fields of different types under a single named roof:

```gg
struct Point3D:
    x: f64
    y: f64
    z: f64

fn main():
    # Initialization with field names:
    p = Point3D{ x: 1.0, y: 2.5, z: -0.5 }
    
    # Accessing fields:
    print("X coordinate:", p.x)
    print("Y coordinate:", p.y)
    
    # Fields can be updated if the variable is not `fixed`:
    mutable_point = Point3D{ x: 0.0, y: 0.0, z: 0.0 }
    mutable_point.x = 10.0
    print("New X:", mutable_point.x)
```

---

## 2. Enumerations (Algebraic Enums)

In Greengold, enums are not just C-style lists of simple integers; **they are algebraic data types (tagged unions) in which every variant can carry a different payload**:

```gg
enum Shape:
    Circle(f64)           # Radius
    Rectangle(f64, f64)   # Width, height
    Point                 # Payload-free (unit) variant

fn main():
    c = Shape.Circle(5.0)
    r = Shape.Rectangle(10.0, 4.0)
    p = Shape.Point
```

To take the data out of an enum safely, you use the `match` construct, which we cover in the next chapter.

---

## 3. Tuples

**Tuples** are used to hold a few related values together temporarily, without defining a separate struct.

### 3.1 Defining a Tuple and Accessing Elements
Tuple types are written as types separated by commas inside parentheses: `(T1, T2, ...)`. Elements are reached with numeric indices such as `.0`, `.1`, `.2`:

```gg
fn main():
    # A tuple with three elements: (i32, f64, str)
    triple = (100, 3.14, "Greengold")
    
    print("Element 0:", triple.0)  # 100
    print("Element 1:", triple.1)  # 3.14
    print("Element 2:", triple.2)  # Greengold
```

> **Compiler note:** Behind the scenes the compiler turns tuples directly into `Tuple2`..`Tuple6` structs (desugaring). Tuples with up to 6 elements are supported; for larger sets of data, defining a `struct` is recommended.

### 3.2 Returning Multiple Values From a Function
The most popular use of tuples is returning more than one result from a function with no effort:

```gg
# A function that returns both the quotient and the remainder at once:
fn divmod(a: i32, b: i32) -> (i32, i32):
    return (a / b, a % b)

fn main():
    res = divmod(17, 5)
    print("Quotient:", res.0, "Remainder:", res.1)
```

---

## 4. Destructuring Assignment

Destructuring splits the elements of a tuple or of a multiple return into separate variables on a single line:

```gg
fn main():
    # Assign directly to separate variables:
    quotient, remainder = divmod(27, 4)
    print("Quotient:", quotient)     # 6
    print("Remainder:", remainder)   # 3

    # The unpacked variables can also be changed (unless you write `fixed x, y = ...`):
    x, y = (10, 20)
    x += 5
    y += 10
    print("Current x, y:", x, y)   # 15, 30
```

### 4.1 Skipping Elements You Do Not Need (`_`)
If you need only some elements of a tuple, you can skip the rest with `_` (wildcard):

```gg
fn get_user_info() -> (i32, str, str):
    return (101, "Ali Veli", "ali@example.com")

fn main():
    # We are only interested in the ID and the email address:
    id, _, email = get_user_info()
    print("User ID:", id, "Email:", email)
```

---

## 5. Type Aliases (`type`)

`type` is used to make complex types easier to understand or to avoid repeating code:

```gg
type Point2D = (f64, f64)
type UserID = u64
type Matrix4x4 = [16]f32

fn distance(p1: Point2D, p2: Point2D) -> f64:
    dx = p1.0 - p2.0
    dy = p1.1 - p2.1
    # Pythagorean formula
    return (dx * dx + dy * dy) # simplified

fn main():
    origin: Point2D = (0.0, 0.0)
    target: Point2D = (3.0, 4.0)
    print("Squared distance:", distance(origin, target))
```

---

## 6. Fixed Arrays (`[N]T`) and Repeat Literals

Fixed-size arrays are allocated on the stack, and their size is known at compile time:

```gg
fn main():
    # An i32 array with 4 elements:
    numbers: [4]i32 = [10, 20, 30, 40]
    print("First element:", numbers[0])
    print("Length:", numbers.len)

    # Creating an array made of 100 zeros (repeat literal):
    zeros: [100]i32 = [0; 100]
    print("Length of the zero array:", zeros.len)
```

---

## 7. Slices (`[]T`)

A slice is a dynamically sized **read-only window (fat pointer: pointer + length)** over an array or a block of memory.

> **Safety rule:** In Greengold, slices cannot be stored in local variables; **they are accepted only as function parameters**. This makes dangling-pointer errors, which could come from the memory behind them going out of scope, impossible.

```gg
# A function that accepts a slice of an array of any size:
fn sum(items: []i32) -> i32:
    total = 0
    for x in items:
        total += x
    return total

fn main():
    data: [5]i32 = [1, 2, 3, 4, 5]
    
    # Passing the whole array as a slice:
    print("Total:", sum(data))          # 15
    
    # Passing a sub-range (subslice) [1..4]:
    print("Part total:", sum(data[1..4])) # 2 + 3 + 4 = 9
```

---

## 8. Practice: A 2D Game Vector and State Model

```gg
# game_model.gg
type Vec2 = (f64, f64)

enum EntityState:
    Idle
    Moving(Vec2)
    Dead

struct Entity:
    id: i32
    position: Vec2
    state: EntityState

impl Entity:
    fn update(self: lend Entity):
        # Update according to the state
        is_moving = false
        # we will go into the match construct in the next chapter
        print("Entity updated, ID:", self.id)

fn main():
    pos: Vec2 = (100.0, 200.0)
    hero = Entity{
        id: 1,
        position: pos,
        state: EntityState.Moving((1.5, 0.0))
    }
    
    hero.update()
    print("Hero X, Y:", hero.position.0, hero.position.1)
```

---

## 🎯 Chapter Summary and Exercises

In this chapter you learned:
* `struct` types with named fields.
* Algebraic `enum` variants that can carry rich payloads.
* `(A, B)` tuples for multiple values, and the `.0`, `.1` indices.
* Destructuring assignments with `a, b = expr` and `_`.
* `type Name = T` type aliases.
* Fixed-size stack arrays `[N]T` and parameter windows `[]T`.

### Try It Yourself:
1. Write a function `min_max(numbers: []i32) -> (i32, i32)` and return the smallest and largest number in the array as a single tuple.
2. Define `type Point = (f64, f64)` and use it by destructuring as `a, b = (1.0, 2.0)`.

Next up is [Chapter 06: Pattern Matching](06_Pattern_Matching.md), where we will query these data structures with skill!
