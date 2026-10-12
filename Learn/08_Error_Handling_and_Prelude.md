# Chapter 08: Error Handling and the Core Library

Tony Hoare called the `null` pointer his billion-dollar mistake: *"It was easy to implement, but it has led to innumerable errors, vulnerabilities, and system crashes, which have probably caused a billion dollars of pain and damage."*

In safe Greengold code **there is no `null` reference**. There are no unhandled runtime exceptions or slow `try-catch` blocks either. **Errors are ordinary, explicit values in the system.**

The Greengold core library (the Prelude) offers two basic generic enums that bring errors into the type system: **`Optional[T]`** and **`Result[T, E]`**.

---

## 1. The Absence of a Value: `Optional[T]`

If a function may or may not return a value, its return type must be `Optional[T]`.

### 1.1 Variants and Short Constructors
`Optional[T]` has two states:
* `Valid(T)` (or `Some(T)` for short): says the value exists.
* `None`: says there is no value.

```gg
# A function that finds the index of an element searched for in an array:
fn find_index(items: []i32, target: i32) -> Optional[usize]:
    for idx, val in items:
        if val == target:
            return Valid(idx)
    return None

fn main():
    numbers: [4]i32 = [10, 25, 40, 85]

    match find_index(numbers, 40):
        Valid(idx):
            print("Element found, index:", idx)
        None:
            print("Element is not in the array!")
```

### 1.2 `Optional` Helper Methods
Practical methods you can use instead of writing a `match` every time:

* **`.has_value()` / `.is_none()`:** Ask about the presence of the value as a boolean (`bool`).
* **`.value_or(default)`:** Returns the contents if the value is `Valid`, or the given default if it is `None`:
  ```gg
  val = find_index(numbers, 99).value_or(0)
  ```
* **`.value_or_panic()`:** Unwraps the value when you are sure it exists. If it is `None`, the program crashes with `panic` (recommended only in tests and prototypes):
  ```gg
  val = find_index(numbers, 25).value_or_panic()
  ```

---

## 2. Operations That Carry an Error: `Result[T, E]`

If the reason an operation failed matters and an error description is needed, `Result[T, E]` is used:

### 2.1 Variants
* `Ok(T)`: The operation succeeded and produced a result of type `T`.
* `Err(E)`: The operation failed and produced an error object of type `E`.

```gg
enum MathError:
    DivisionByZero
    NegativeSquareRoot

fn safe_divide(a: f64, b: f64) -> Result[f64, MathError]:
    if b == 0.0:
        return Err(MathError.DivisionByZero)
    return Ok(a / b)

fn main():
    match safe_divide(10.0, 0.0):
        Ok(res):
            print("Result:", res)
        Err(e):
            match e:
                MathError.DivisionByZero:
                    print("Error: division by zero prevented!")
                MathError.NegativeSquareRoot:
                    print("Error: negative root!")
```

---

## 3. The `?` Error Propagation Operator (Try Operator)

As functions grow, writing nested `match`es makes the code complicated. With the Rust-like **`?` operator**, Greengold lets you throw errors upward automatically.

If the called function returns `Ok(val)`, the `?` operator takes the value out (`val`). If it returns `Err(e)`, the function you are in stops immediately and returns the error to its caller!

```gg
fn step_one() -> Result[i32, str]:
    return Ok(10)

fn step_two(x: i32) -> Result[i32, str]:
    if x > 5:
        return Ok(x * 2)
    return Err("x is too small")

# The main flow that combines the two steps:
fn execute_workflow() -> Result[i32, str]:
    # If step_one returns an error, the function returns right here:
    val1 = step_one()?
    
    # If step_two returns an error, it returns here:
    val2 = step_two(val1)?
    
    return Ok(val2 + 5)

fn main():
    match execute_workflow():
        Ok(final_val):
            print("Operation succeeded:", final_val)
        Err(err_msg):
            print("Operation failed:", err_msg)
```

### 3.1 Rules for Using the `?` Operator
To guarantee readability and evaluation order, in Greengold `?` can be used **only in full expressions**:

```gg
x = f()?        # Valid
x = f()?         # Valid
return f()?      # Valid
f()?             # Valid (if the result is to be discarded)

# g(f()?)        <-- COMPILE ERROR! ? cannot be used inside a sub-expression.
# x += f()?      <-- COMPILE ERROR!
```

---

## 4. Automatic Error Type Conversion (`Target.from`)

With Greengold v4, when you combine libraries that produce different error types, the `?` operator converts types automatically!

If the calling function returns `Result[T, AppError]` but the called function returns `Result[T, i32]`, and a `fn from(e: i32) -> AppError` is defined in an `impl AppError:` block, the compiler applies the conversion automatically:

```gg
enum AppError:
    Database(i32)
    Network(str)

impl AppError:
    # Converts an i32 error code to an AppError:
    fn from(code: i32) -> AppError:
        return AppError.Database(code)

fn query_db() -> Result[str, i32]:
    return Err(500) # Database error code

fn handle_request() -> Result[str, AppError]:
    # Although query_db() returns Result[str, i32], it is converted to AppError automatically with ?!
    data = query_db()?
    return Ok(data)

fn main():
    if let Err(e) = handle_request():
        print("Application error caught!")
```

---

## 5. Unrecoverable Errors: `panic`

If the program has run into a critical logic error or a hardware limit that it cannot continue past, the process is ended in a controlled way with `panic`:

```gg
fn access_kernel_resource(level: i32):
    if level < 0:
        panic("Critical error: invalid kernel permission level!")
    print("Access granted")
```

When `panic` is called:
* The error message is written to the `stderr` stream.
* The program ends immediately with exit code 101.
* In bare-metal / embedded system modes (`--target bare-metal`) it turns into the `llvm.trap` machine trap.

---

## 6. Practice: A Safe Text Parser

```gg
# parser_demo.gg
enum ParseError:
    EmptyInput
    InvalidFormat

fn parse_positive_number(input: str) -> Result[i32, ParseError]:
    if input.len == 0:
        return Err(ParseError.EmptyInput)
        
    total = 0
    for i in 0..input.len:
        c = input[i]
        if c < '0' or c > '9':
            return Err(ParseError.InvalidFormat)
        total = total * 10 + i32(c - '0')
        
    return Ok(total)

fn main():
    inputs: [3]str = ["1234", "", "42a"]
    
    for s in inputs:
        match parse_positive_number(s):
            Ok(num):
                print("Parsed:", num)
            Err(e):
                match e:
                    ParseError.EmptyInput:
                        print("Error: input is empty!")
                    ParseError.InvalidFormat:
                        print("Error: contains an invalid character ->", s)
```

---

## 🎯 Chapter Summary and Exercises

In this chapter you learned:
* Greengold has no hidden `null`; absence is expressed with `Optional[T]`.
* Errors are brought into the type system with `Result[T, E]`.
* The `?` operator propagates errors upward with an early return.
* With the `Target.from(e)` method, different error types are converted automatically through `?`.
* `panic` is used for unrecoverable system crashes.

### Try It Yourself:
1. Write a function `validate_age(age: i32) -> Result[i32, str]` (`Err` if the age is below 0 or above 150, `Ok` otherwise).
2. Design a function `register_user(name: str, age: i32)` that calls this function and uses `?`.

Now we are ready to move on to the standard library: [Chapter 09: Standard Library and Concurrency](09_Standard_Library_and_Concurrency.md)!
