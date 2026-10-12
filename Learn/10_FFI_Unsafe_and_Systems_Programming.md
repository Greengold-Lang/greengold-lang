# Chapter 10: FFI, Raw Pointers, and Systems Programming

For a language to be a real **systems programming language**, it must be able to talk directly to operating system kernels, C libraries, graphics APIs (OpenGL, Vulkan), and raw hardware addresses.

Greengold talks to C libraries directly over the C ABI with zero interface overhead. But to keep the principle of type and memory safety, it draws a firm boundary between the **safe world (safe code)** and the **raw world (unsafe code)**.

---

## 1. Declaring External C Functions (`extern`)

The `extern` keyword is used to call an existing C library or the standard C runtime (libc):

```gg
# Binding functions from the C standard math library:
extern "math.h" fn sin(x: f64) -> f64
extern "math.h" fn cos(x: f64) -> f64

# printf and puts from the C standard I/O library:
extern "stdio.h" fn puts(s: *u8) -> i32
extern "stdio.h" fn printf(fmt: *u8, ...) -> i32
```

### 1.1 Functions With a Variable Number of Parameters (`...`)
Variadic functions such as C's `printf` are marked with `...` in the signature. Calling a variadic function needs raw C pointers, so it can only be done inside an `unsafe:` block.

---

## 2. C-Compatible Data Structures (`extern struct`)

Greengold's own internal struct layout can be optimized by the compiler. But a struct that will be passed to C functions must match exactly the memory layout (alignment/padding) that C compilers expect. `extern struct` is used for this:

```gg
# A memory layout 100% compatible with the C ABI:
extern struct Point2D:
    x: f32
    y: f32

extern struct RectInfo:
    top_left: Point2D
    width: i32
    height: i32
```

> **Rule:** The fields of an `extern struct` can only be primitive numbers, booleans, raw pointers, or other `extern struct`s (they cannot contain heap types such as `Box` or `List`).

---

## 3. Raw Pointers

In safe Greengold code, references are managed with `lend` or `ref`; in FFI and low-level hardware access, **raw pointers** come into play:

| Pointer type | Description | C equivalent |
|---|---|---|
| `*T` | Read-only raw pointer | `const T*` |
| `*mut T` | Writable raw pointer | `T*` |
| `*void` | Type-independent raw pointer | `void*` |

### 3.1 The `null` Value
A raw pointer that points nowhere can take the value `null`, or be compared with `null`:

```gg
fn check_pointer(ptr: *i32) -> bool:
    # Comparing with null is allowed in safe code:
    return ptr != null
```

---

## 4. The Safety Boundary: `unsafe:` Blocks

In Greengold, dereferencing raw pointers (reading/writing the data at the address they point to), doing pointer arithmetic, or calling raw C functions is possible **only and exclusively inside `unsafe:` blocks**.

When the compiler sees an `unsafe:` block, it is saying:
> *"The compiler's safeguards switch off here; memory safety, bounds checks, and pointer validity are entirely the programmer's responsibility."*

```gg
# C stdio functions
extern "stdio.h" fn puts(str_ptr: *u8) -> i32

fn main():
    unsafe:
        # Call the C function:
        puts(string_to_cstr("Hello from the C library!"))
```

---

## 5. Raw Pointer Helper Functions

Greengold provides built-in special functions for working with pointers (all of them require `unsafe:`):

* **`addr(x)` / `addr_mut(x)`:** Takes the memory address of a variable as `*T` or `*mut T`.
* **`ptr_offset(ptr, offset)`:** Moves the pointer forward or backward in memory (`ptr + offset`).
* **`ptr_cast[*Target](ptr)`:** Converts the pointer type to another type (`reinterpret_cast`).
* **`ptr_to_int(ptr)` / `int_to_ptr(addr)`:** Converts between a pointer and an integer.
* **`string_to_cstr(s)`:** Turns a Greengold `str` slice into the null-terminated `*u8` pointer C expects.
* **`cstr_to_string(p)`:** Converts a null-terminated string coming from C into a Greengold `str` slice.
* **`str_from_raw(ptr, len)`:** Builds a safe `str` view from a raw address and a length.

```gg
fn main():
    number: i32 = 42

    unsafe:
        # 1. Take the memory address:
        p: *mut i32 = addr_mut(number)
        
        # 2. Read and change the pointed-to data:
        p[0] = 99
        
    print("Updated number:", number)  # 99
```

---

## 6. Writing Safe Wrappers

In professional systems programming, the best practice is to confine `unsafe` code inside small functions and offer the outside world a **100% safe** API:

```gg
# The C standard rand() and srand() functions:
extern "stdlib.h" fn rand() -> i32
extern "stdlib.h" fn srand(seed: u32)

# A 100% safe Greengold wrapper for users:
fn get_c_random(max: i32) -> i32:
    if max <= 0:
        return 0
        
    unsafe:
        raw_val = rand()
        return raw_val % max

fn main():
    # The caller does not need to write unsafe!
    dice = get_c_random(6) + 1
    print("Dice result:", dice)
```

---

## 7. Practice: Inspecting Memory Bytes Directly (Hex Dumper)

```gg
# memory_inspector.gg
struct Header:
    magic: u32
    version: u16
    flags: u16

fn inspect_bytes(ptr: *u8, count: usize):
    unsafe:
        for i in 0..count:
            byte_val = ptr[i]
            print("Offset", i, ": 0x", byte_val)

fn main():
    h = Header{ magic: 0xDEADBEEF, version: 1, flags: 0x00FF }
    
    print("Dump of the Header memory bytes:")
    unsafe:
        raw_bytes = ptr_cast[*u8](addr(h))
        inspect_bytes(raw_bytes, 8)
```

---

## 🎯 Chapter Summary and Exercises

In this chapter you learned:
* Binding C functions and the C ABI with `extern`.
* `extern struct` for a C-compatible memory layout.
* The raw pointers `*T`, `*mut T`, `*void`, and `null`.
* The safety-boundary philosophy of `unsafe:` blocks.
* Hardware-level operations such as `addr`, `ptr_cast`, and `ptr_offset`.
* Developing safe API wrappers.

### Try It Yourself:
1. Bind the `sqrt` function from the C standard library with `extern "math.h"` and write a safe wrapper `square_root(x: f64) -> Result[f64, str]` (it should return `Err` for negative numbers).

We have completed all the language fundamentals! Now you can move on to [Chapter 11: Project Management and Developer Tools](11_Project_Management_and_Tooling.md), where you will build and manage your projects professionally!
