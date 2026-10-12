# Chapter 06: Pattern Matching

Pattern matching is the most advanced control flow tool. It lets you examine and take apart not only the value of data, but its **shape, kind, and contents** at the same time.

Unlike the limited integer logic of `switch` statements in C/Java, Greengold's `match` checks algebraic enums, scalar values, ranges, and alternatives exhaustively at compile time.

---

## 1. The `match` Statement and Exhaustiveness

When you write a `match` in Greengold, the compiler makes sure that **all possible cases** of the examined type are handled. If a variant or case is forgotten, the code does not compile!

```gg
enum TrafficLight:
    Red
    Yellow
    Green

fn action(light: TrafficLight):
    match light:
        TrafficLight.Red:
            print("Stop!")
        TrafficLight.Yellow:
            print("Get ready...")
        TrafficLight.Green:
            print("Go!")
```

### 1.1 Catching the Remaining Cases: the Wildcard (`_`)
If you do not want to write out every variant, `_:` is used to cover everything else:

```gg
fn is_stop_signal(light: TrafficLight) -> bool:
    match light:
        TrafficLight.Red:
            return true
        _:
            return false
```

---

## 2. Extracting Algebraic Enum Payloads

To extract the data carried by enum variants, variable names are declared inside the pattern:

```gg
enum Shape:
    Circle(f64)
    Rectangle(f64, f64)
    Point

fn describe_shape(s: Shape):
    match s:
        Shape.Circle(radius):
            print("A circle with radius", radius)
        Shape.Rectangle(width, height):
            print("A rectangle with size", width, "x", height)
        Shape.Point:
            print("A point with no size")
```

You can ignore a field you are not interested in with `_`:

```gg
fn get_width(s: Shape):
    match s:
        Shape.Rectangle(w, _):
            print("Width only:", w)
        _:
            pass
```

---

## 3. `match` Modes (`read`, `lend`, `consume`)

Like function parameters, a `match` statement can work in different ownership modes:

* **`match s:` (default - read):** It only examines the data; the payloads are read-only.
* **`match lend s:`:** Used to change the payload inside a variant in place.
* **`match consume s:`:** Consumes the ownership of the variable and moves the payloads to their new owners.

```gg
enum Item:
    Weapon(i32)
    Empty

fn upgrade_weapon(item: lend Item):
    match lend item:
        Item.Weapon(power):
            # power is a lend reference here, it is updated directly:
            power += 10
        Item.Empty:
            pass

fn main():
    sword = Item.Weapon(50)
    upgrade_weapon(sword)
    
    match sword:
        Item.Weapon(p):
            print("Upgraded power:", p)  # 60
        Item.Empty:
            pass
```

---

## 4. Scalar Values, Ranges, and Alternatives

`match` is not limited to enums. It also works on integers, characters, booleans, and strings:

### 4.1 Multiple Alternatives (`|`) and Ranges (`..=`)

```gg
fn classify_http_status(code: i32):
    match code:
        200 | 201 | 204:
            print("Success")
        301 | 302:
            print("Redirect")
        400..=499:
            print("Client error (4xx)")
        500..=599:
            print("Server error (5xx)")
        _:
            print("Unknown status code")

fn check_char(c: u8):
    match c:
        'a'..='z' | 'A'..='Z':
            print("Letter")
        '0'..='9':
            print("Digit")
        _:
            print("Special character")
```

---

## 5. `match` as an Expression (Inline Values With `=>`)

You can assign the result of a `match` block directly to a variable or return it from a function. Each arm is tied to a single expression with `=>` (the fat arrow):

```gg
fn error_message(code: i32) -> str:
    return match code:
        0 => "Success"
        1 => "File not found"
        2 => "Access denied"
        _ => "General system error"

fn main():
    status_code = 2
    msg = match status_code:
        0 => "OK"
        _ => "Error!"
        
    print(msg)
```

---

## 6. Modern Conditional Matching: `if let` and `while let`

Added in Greengold v4, `if let` and `while let` make your code much simpler when you care about only one variant.

### 6.1 `if let`: Checking a Single Pattern
Instead of writing a `match` and saying `_ => pass` for the rest:

```gg
fn main():
    # An Optional value
    maybe_number: Optional[i32] = Valid(42)

    # If the value is `Valid(x)`, bind x and run the block:
    if let Valid(x) = maybe_number:
        print("Number found:", x)
    else:
        print("No number!")
```

### 6.2 `while let`: Loops That Run While the Pattern Matches
It is especially good with structures such as a stack, a queue, or a stream that hand out elements until they run out:

```gg
fn main():
    stack = List[str]()
    stack.push("First")
    stack.push("Second")
    stack.push("Third")

    # List.pop() returns `Valid(item)` until it is exhausted, then `None`:
    while let Valid(item) = stack.pop():
        print("Popped from the stack:", item)
```

Output:
```text
Popped from the stack: Third
Popped from the stack: Second
Popped from the stack: First
```

---

## 7. Practice: A Calculator Command Interpreter

```gg
# calc_eval.gg
enum Command:
    Add(f64, f64)
    Subtract(f64, f64)
    Square(f64)
    Reset

fn evaluate(cmd: Command) -> f64:
    return match cmd:
        Command.Add(a, b) => a + b
        Command.Subtract(a, b) => a - b
        Command.Square(x) => x * x
        Command.Reset => 0.0

fn main():
    commands: [4]Command = [
        Command.Add(10.0, 5.0),
        Command.Square(4.0),
        Command.Subtract(20.0, 8.0),
        Command.Reset
    ]

    for c in commands:
        result = evaluate(c)
        print("Calculation result:", result)
```

---

## 🎯 Chapter Summary and Exercises

In this chapter you learned:
* The compile-time exhaustiveness guarantee of `match`.
* Binding algebraic enum payloads to variables or to the `_` wildcard.
* Matching that fits the memory mode, with `match lend` and `match consume`.
* Scalar alternatives (`|`) and ranges (`..=`).
* The one-line expression form `match ... =>`.
* Practical pattern matching with `if let` and `while let`.

### Try It Yourself:
1. Write a division function that returns `Result[i32, str]` (`divide(a: i32, b: i32)`). Catch the success case with `if let Ok(res) = divide(10, 2)`.
2. Set up a `while let Valid(n) = ...` loop that consumes the positive numbers of an array one by one and prints their total.

Next is [Chapter 07: Generics, Features, and Operator Overloading](07_Generics_Features_and_Operator_Overloading.md), which takes the language's power of abstraction to its peak!
