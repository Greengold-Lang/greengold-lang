# Chapter 02: Control Flow and Loops

Real-world programs must make decisions based on conditions and repeat operations over data. Greengold supports both classic control flow structures and a modern, expression-based syntax.

---

## 1. Conditionals (`if`, `elif`, `else`)

Greengold does not require parentheses around conditions. After the condition comes a colon (`:`), and the next line opens a block indented by 4 spaces.

```gg
fn main():
    score = 85

    if score >= 90:
        print("Grade: A")
    elif score >= 80:
        print("Grade: B")
    elif score >= 70:
        print("Grade: C")
    else:
        print("Grade: F")
```

### 1.1 `if` as an Inline Expression (`if ... then ... else`)
In Greengold, `if` can be used as an inline expression that produces a value (a more readable form of the ternary operator):

```gg
fn main():
    age = 20
    # We assign the result of the condition directly to status:
    status = if age >= 18 then "Adult" else "Child"
    print(status)

    score = 75
    grade = if score >= 90 then "A" elif score >= 70 then "B" else "C"
    print("Grade:", grade)
```

> **Important rule:** If an `if` expression returns a value, all branches (`then`, `elif`, `else`) must return a value of **exactly the same type**, and the `else` branch is required.

---

## 2. The `while` Loop

The classic loop that keeps running as long as a boolean condition is true:

```gg
fn main():
    n = 5
    while n > 0:
        print("Countdown:", n)
        n -= 1
    print("Fire!")
```

---

## 3. Rich `for` Loops

Greengold's `for` loop is quite powerful and offers practical syntax for different use cases.

### 3.1 Exclusive Range Loop (`..`)
The start is included, the end is excluded (`[start, end)`):

```gg
fn main():
    # From 0 up to 5 (0, 1, 2, 3, 4)
    for i in 0..5:
        print("i:", i)
```

### 3.2 Inclusive Range Loop (`..=`)
Both the start and the end are included (`[start, end]`):

```gg
fn main():
    # From 1 to 5 (1, 2, 3, 4, 5)
    for i in 1..=5:
        print("Number:", i)
```

### 3.3 Stepped Loops (`step`)
`step` moves through ranges with a given step (positive or negative):

```gg
fn main():
    # Even numbers: 0, 2, 4, 6, 8
    for i in 0..10 step 2:
        print("Even:", i)

    # Stepping backwards: 10, 8, 6, 4, 2
    for i in 10..0 step -2:
        print("Back:", i)
```

### 3.4 Short Count Loop
When you give a plain integer, it stands for the range `0..n`:

```gg
fn main():
    # From 0 up to 3 (0, 1, 2)
    for i in 3:
        print("Round:", i)
```

---

## 4. Iterating Over Collections

### 4.1 Iterating Over Elements (`for item in collection`)
You loop directly over the elements of fixed-size arrays or dynamic lists:

```gg
fn main():
    primes: [4]i32 = [2, 3, 5, 7]
    for p in primes:
        print("Prime:", p)
```

### 4.2 Iterating With an Index (`for index, item in collection`)
If you also need the position (index) of the element in the loop, you can bind two variables separated by a comma (`k: usize`, `x: Element`):

```gg
fn main():
    names: [3]str = ["Ali", "Ayse", "Zeynep"]
    for idx, name in names:
        print(idx, name)
        # Output:
        # 0 Ali
        # 1 Ayse
        # 2 Zeynep
```

### 4.3 Changing Elements in Place (`for item in collection`)
If the body of `for item in list` does not change `item`, `item` is read-only. If the body changes `item` (an assignment or a method that changes it), `item` borrows each element with `lend`, and the change is written directly into the collection. The editor shows this with the `: lend i32` hint:

```gg
fn main():
    numbers: [3]i32 = [10, 20, 30]
    
    for num in numbers:
        num *= 2    # the elements of the numbers array are doubled in place
        
    for n in numbers:
        print(n)    # prints 20, 40, 60
```

---

## 5. Loop Control: `break`, `continue`, `pass`

* **`break`:** Ends the loop immediately.
* **`continue`:** Skips the current iteration and moves on to the next one.
* **`pass`:** Used when an empty block is needed (as in Python). Greengold does not allow blocks with an empty body; write `pass` where you leave one empty on purpose.

```gg
fn main():
    for i in 0..10:
        if i == 3:
            continue    # skip 3
        if i == 7:
            break       # leave the loop at 7
        print(i)        # prints 0, 1, 2, 4, 5, 6

    # An example of a block with an empty body:
    if true:
        pass
```

---

## 6. Writing Custom Iterators

With Greengold v4 you can make any data structure you like iterable with a `for` loop! All you have to do is define the method `next(self: lend Self) -> Optional[T]`.

```gg
# iterator_demo.gg
struct RangeStepper:
    current: i32
    max: i32
    step_by: i32

impl RangeStepper:
    fn next(self: lend RangeStepper) -> Optional[i32]:
        if self.current > self.max:
            return None
        val = self.current
        self.current += self.step_by
        return Valid(val)

fn main():
    stepper = RangeStepper{ current: 5, max: 20, step_by: 5 }
    
    # The compiler notices RangeStepper's `next` method on its own!
    for x in stepper:
        print("Step value:", x)
```

Output:
```text
Step value: 5
Step value: 10
Step value: 15
Step value: 20
```

---

## 7. Practice: Prime Number Finder

Let's use the control flow structures we have learned to write a program that finds the prime numbers between 2 and 30:

```gg
# primes.gg
fn main():
    print("Prime numbers up to 30:")
    
    for candidate in 2..=30:
        is_prime = true
        
        # Check whether any number from 2 up to candidate divides it
        for divisor in 2..candidate:
            if candidate % divisor == 0:
                is_prime = false
                break
                
        if is_prime:
            print(candidate)
```

---

## 🎯 Chapter Summary and Exercises

In this chapter you learned:
* `if/elif/else` blocks and one-line `if cond then A else B` expressions.
* All forms of `while` and `for` loops (`..`, `..=`, `step`, count).
* Indexed iteration (`k, x`) over collections and iteration that changes elements in place.
* Making your own type iterable with the `next()` method.

### Try It Yourself:
1. Loop over the numbers from `1..=100`. Print `"Fizz"` for those divisible by 3, `"Buzz"` for those divisible by 5, `"FizzBuzz"` for those divisible by both, and the number itself otherwise.
2. Create an array of type `[5]i32` and replace all negative numbers with 0 using a `for` loop.

When you are ready, you can move on to [Chapter 03: Functions, Methods, and Lambdas](03_Functions_Methods_and_Lambdas.md)!
