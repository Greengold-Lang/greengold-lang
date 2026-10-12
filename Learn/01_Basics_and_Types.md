# Chapter 01: Basics and Types

Every programming language has a backbone and rules of grammar. In this chapter you will learn Greengold's syntax structure, its philosophy of declaring variables, its primitive data types, and its operators.

---

## 1. Anatomy of a Greengold Program

Greengold has a clean, Python-like syntax and produces machine code at the level of C and Rust. Blocks are defined by **indentation** instead of curly braces (`{}`).

```gg
# main.gg
fn main():
    print("Welcome to Greengold!")
```

### Important Syntax Rules:
1. **Indentation rule:** Code blocks are indented with **exactly 4 spaces**. Using a tab character (`\t`) is a compile error. This rule removes indentation inconsistency from code bases entirely.
2. **Comments:** Comments start with the `#` symbol. C-style `//` comments are not accepted; if you write one by accident, the compiler warns you:
   ```gg
   # A valid comment line
   # print("this does not run")
   ```

---

## 2. Variables and `fixed`

In Greengold **variables are mutable by default**. No extra keyword is needed.

### 2.1 Short Declaration (`=`)
The most common way to declare a variable. The type is inferred from the expression on the right (type inference):

```gg
fn main():
    x = 42           # x is a variable of type i32
    name = "Ahmet"   # name is a str, a string slice
    x = 50            # it can be changed
    print(x, name)
```

### 2.2 Explicitly Typed Declaration (`: Type =`)
When you want to state the type yourself instead of leaving it to the compiler:

```gg
fn main():
    pi: f64 = 3.1415926535
    age: u8 = 25
```

### 2.3 Variables That Never Change (`fixed`)
If you want a value to never change, write **`fixed`** in front. Assigning to it afterwards, lending it with `lend`, or calling a method that changes it is a compile error:

```gg
fn main():
    fixed limit = 10
    # limit = 20   <-- COMPILE ERROR! `limit` was declared fixed.
    print(limit)
```

The compiler already treats a variable that is never changed anywhere as `fixed`. In this case VS Code shows a faint **`fixed`** inlay hint in front of the variable; the hint disappears as soon as you change the variable somewhere. So you can see which values stay constant even without writing `fixed`.

For a counter that changes, you do not need to add anything:

```gg
fn main():
    counter = 0
    counter += 1
    counter = counter * 2
    print(counter)    # prints 2

    total: i64 = 100
    total -= 15
    print(total)      # prints 85
```

### 2.4 Global Constants (`const`)
`const` is used for values defined at file level, outside functions, and known at compile time:

```gg
const MAX_BUFFER_SIZE: usize = 4096
const APP_NAME = "Greengold Engine"

fn main():
    print(APP_NAME, MAX_BUFFER_SIZE)
```

---

## 3. Primitive Data Types

Greengold has a rich set of integer and floating-point types that give full control at the hardware level:

### 3.1 Integers

| Type | Bit width | Range | Description |
|---|---|---|---|
| `i8` | 8-bit | -128 .. 127 | Signed byte |
| `i16` | 16-bit | -32,768 .. 32,767 | Signed short integer |
| `i32` | 32-bit | -2,147,483,648 .. 2,147,483,647 | **Default integer type** |
| `i64` | 64-bit | -9.22 × 10¹⁸ .. 9.22 × 10¹⁸ | Large integer |
| `isize` | Platform size | 32-bit or 64-bit | Signed memory offsets |
| `u8` | 8-bit | 0 .. 255 | Unsigned byte / ASCII character |
| `u16` | 16-bit | 0 .. 65,535 | Unsigned short integer |
| `u32` | 32-bit | 0 .. 4,294,967,295 | Unsigned integer |
| `u64` | 64-bit | 0 .. 1.84 × 10¹⁹ | Large unsigned integer |
| `usize` | Platform size | 32-bit or 64-bit | **Array/collection index and length type** |

### 3.2 Floating-Point Numbers
* `f32`: 32-bit IEEE 754 single-precision floating-point number.
* `f64`: 64-bit IEEE 754 double-precision floating-point number (**default float type**).

### 3.3 Booleans (`bool`)
It can have only two values: `true` or `false`.

```gg
fn main():
    is_active = true
    has_permission: bool = false
    print(is_active and not has_permission)
```

### 3.4 Text and Character Types
* **Character literal (`'c'`):** Written with single quotes and has the value of a `u8`.
* **String slice (`str`):** Written with double quotes. It is an immutable, UTF-8 encoded view of memory.

```gg
fn main():
    ch = 'A'              # ch is a u8 value (ASCII 65)
    greeting = "Hello"    # greeting is a str
    print(ch, greeting)
```

---

## 4. Numeric Literals and Escape Sequences

You can use underscores (`_`) to write large numbers readably:

```gg
fn main():
    # Number bases and underscores
    million = 1_000_000
    hex_color = 0xFF_57_33
    bin_mask = 0b1100_0011
    small_float = 0.000_001

    print(million, hex_color, bin_mask, small_float)
```

### Escape Sequences
The following escape sequences are supported in strings and characters:
* `\n`: Newline
* `\t`: Tab
* `\r`: Carriage return
* `\\`: Backslash
* `\"`: Double quote
* `\'`: Single quote
* `\0`: Null byte (**valid only in character literals; `\0` is forbidden in strings**)

---

## 5. Type Casting

Greengold does **lossless** conversions by itself: a small integer to a wider integer (`i32` → `i64`, `u8` → `i32`), `f32` to `f64`, and an integer to a float that holds it exactly (`i32` → `f64`). If the two sides of an operation differ, the narrower side widens. Conversions that could lose a value (`i64` → `i32`, `f64` → `i32`, `i32` → `usize`) are written by you; next to the error, the compiler also suggests the `i32(...)` fix:

```gg
fn main():
    a: i32 = 100
    b: i64 = 200

    c = a + b         # Valid: a becomes i64 on its own, c is an i64.
    ratio: f64 = a     # Valid: every i32 value fits exactly in an f64.

    val: f64 = 9.81
    truncated = i32(val) # This loses a value (truncated to 9), so it is written explicitly.
    print(c, ratio, truncated)
```

---

## 6. Operators and Precedence

To avoid C's well-known precedence trap, Greengold adopts Python's precedence order: bitwise operators (`&`, `|`, `^`) bind more tightly than comparisons (`==`, `!=`). So `bits & 1 == 0` means `(bits & 1) == 0`, as expected.

```gg
fn main():
    # Arithmetic
    sum = 10 + 20
    diff = 30 - 5
    prod = 4 * 6
    quot = 20 / 3    # Integer division: 6
    rem = 20 % 3     # Remainder: 2

    # Comparison
    is_equal = (sum == 30)
    is_greater = (sum > 25)

    # Logical
    both = is_equal and is_greater
    either = is_equal or false
    inverted = not both

    # Bitwise operations
    bits = (0b1010 & 0b1100) | 0b0001
    shifted = 1 << 4  # 16
    
    print(sum, is_equal, bits, shifted)
```

---

## 7. Practice: Temperature Converter

Let's write a small example that brings together what we have learned:

```gg
# temp_converter.gg
const FREEZING_POINT_F: f64 = 32.0

fn main():
    celsius = 25.0
    
    # C to F formula: (C * 9/5) + 32
    fahrenheit = (celsius * 9.0 / 5.0) + FREEZING_POINT_F
    print("Celsius:", celsius)
    print("Fahrenheit:", fahrenheit)

    # The reverse
    fahrenheit = 98.6
    celsius_recalculated = (fahrenheit - FREEZING_POINT_F) * 5.0 / 9.0
    print("Body temperature (C):", celsius_recalculated)
```

---

## 🎯 Chapter Summary and Exercises

In this chapter you learned:
* Greengold relies on 4-space indented blocks and `#` comments.
* Variables are mutable by default (`=` or `: Type =`).
* Write `fixed` for values that must never change; variables that are never changed count as `fixed` automatically.
* The type system is strong and static; only lossless conversions happen on their own, and the others are written as `T(...)`.

### Try It Yourself:
1. Try a Fibonacci calculation: update `a = 0` and `b = 1` to print the first 5 numbers in order.
2. Define a radius of type `f32` and compute the area of the circle (`pi * r * r`). Define `pi` as a `const`.

Now you can move on to the next step, [Chapter 02: Control Flow and Loops](02_Control_Flow.md)!
