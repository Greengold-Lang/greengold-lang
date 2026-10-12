# Chapter 04: Ownership, Modes, and Memory

The hardest topic in systems programming languages is **memory management**. In C, memory errors (segfaults, memory leaks, dangling pointers) are left entirely to the developer's care; languages like Rust solve them in the compiler with complex lifetime syntax such as `'a` and `'b`.

**Greengold offers a third, much more balanced way:**
Without complex lifetime parameters, it provides 100% memory safety and C performance through **three explicit parameter modes (`read`, `lend`, `consume`)**, a **Copy/Move type distinction**, and automatic cleanup at the end of a scope (**automatic drop / `defer`**).

---

## 1. The Three Parameter Modes

When you pass an argument to a function, the fate of the data is decided by one of these three modes:

```
+------------+--------------------------------+--------------------------------+
| Mode       | Meaning                        | Effect at the call site        |
+------------+--------------------------------+--------------------------------+
| read       | Read-only (default)            | Data is read, not changed      |
| lend       | Borrow & change in place       | Changes are seen by the caller |
| consume    | Ownership transfer (move)      | Variable can NOT be used again!|
+------------+--------------------------------+--------------------------------+
```

### 1.1 When No Mode Is Written
If no mode is written, copyable types (numbers, structs with no heap part) are copied and the parameter cannot be changed. `p: read T` is always a reference, not a copy. No mode is written at the call site.

Heap-owning types (`List`, `Box`, `string`, and types that contain them) are not copied. If no mode is written, the compiler **infers the mode from the body**: if the parameter is only read it becomes `read`, if it is changed it becomes `lend`, and if it is moved to another owner it becomes `consume`. The caller is checked against this mode; if there is an error, the message shows the inferred mode and the reason.

```gg
struct Bag:
    items: List[i32]

fn add(xs: List[i32]):          # the body changes xs -> lend
    xs.push(1)

fn total(xs: List[i32]) -> i32:  # only reads -> read
    t = 0
    for x in xs:
        t += x
    return t

fn wrap(xs: List[i32]) -> Bag:   # moves into another owner -> consume
    return Bag{ items: xs }

fn main():
    v = List[i32]()
    add(v)                       # add changes v; v must not be `fixed`
    print(total(v))
    b = wrap(v)                 # v cannot be used after this
    print(b.items.len)
```

```gg
struct Player:
    health: i32

# `p: Player` copies (if Player is not heap-owning). `p: read Player` is a reference; the two are not the same thing.
fn show_health(p: Player):
    print("Current health:", p.health)
    # p.health -= 10   <-- COMPILE ERROR! A read parameter cannot be changed.

fn main():
    hero = Player{ health: 100 }
    show_health(hero)   # hero is not changed, it is read safely
```

### 1.2 The `lend` Mode (Borrow & Update in Place)
It lets the function borrow the object temporarily and change it. The variable passed to the function at the call site must not be **`fixed`**:

```gg
fn take_damage(p: lend Player, amount: i32):
    p.health -= amount   # Updated directly on the caller's variable

fn inc(n: lend i32):
    n += 1               # lend works with primitive types too!

fn main():
    hero = Player{ health: 100 }
    take_damage(hero, 25)
    print(hero.health)   # prints 75

    score = 10
    inc(score)
    print(score)         # prints 11
```

### 1.3 The `consume` Mode (Ownership Transfer - Move)
This hands the ownership of an object to another function. A variable that is `consume`d is **no longer valid and cannot be read** after the function call:

```gg
fn archive_player(p: consume Player):
    print("Player archived:", p.health)
    # p's memory ends when this function's scope ends

fn main():
    hero = Player{ health: 100 }
    archive_player(hero)  # the parameter is `consume`, so ownership is handed over; `consume` is not written at the call site

    # print(hero.health)
    # ^ COMPILE ERROR! 'hero' was consumed and can no longer be used!

    # If it is assigned again, the variable comes back to life:
    hero = Player{ health: 50 }
    print(hero.health)            # Valid: prints 50
```

---

## 2. Copyable (Copy) and Movable (Move) Types

In Greengold, the memory behavior of every type is decided by its type:

### 2.1 Copy Types
These are types that live only on the stack and are trivially cheap for the CPU to copy:
* All integers (`i8`..`i64`, `u8`..`u64`, `usize`, `isize`)
* Floating-point numbers (`f32`, `f64`)
* `bool`
* `str` (a read-only text slice)
* Raw pointers (`*T`, `*mut T`)
* Fixed-size arrays that contain only Copy types (`[4]i32`) and plain structs

> **Rule:** Moving a copyable type with `consume` is unnecessary and is rejected by the compiler.

### 2.2 Move Types
These are types that own heap memory or manage a resource:
* `Box[T]` (a single value on the heap)
* `List[T]` (a dynamic list on the heap)
* `string` (text that can grow on the heap)
* Every `struct` and `enum` that contains these types

These types are never copied (this prevents double-free). When they are assigned to another owner they are moved; `consume` is written only on a parameter:

```gg
fn main():
    list_a = List[i32]()
    list_a.push(10)

    list_b = list_a            # Ownership passed to list_b (a move, not a copy).
    list_c = list_b.clone()    # An independent copy: list_b can still be used.
    
    # list_a.push(20)           <-- COMPILE ERROR! list_a was moved.
    print(list_b.len)
```

---

## 3. Automatic Memory Release (Automatic `drop`)

Greengold has no garbage collector. When a Move type (`List`, `Box`, `string`) reaches the end of the scope it was defined in, the compiler calls its **`drop`** code in the background and frees the memory:

```gg
fn process():
    data = List[i64]()
    data.push(100)
    data.push(200)
    
    if true:
        inner_box = Box[i32](42)
        # inner_box is dropped automatically here!
        
    # data is dropped automatically here!
```

---

## 4. Stored References (`read` / `lend`) and Returns (`-> ref` / `-> lend`)

`read T` and `lend T` are not owners: in memory a `T*` sits there, and it is not `drop`ped. Besides being a parameter, one can also be held in a variable and in a struct field.

```gg
r: read Player = hero
w: lend Player = hero
r2 = read hero
n = name_of(hero)          # the mode is inferred if the right side is already a reference

struct Slot:
    who: read Player tied to self
```

`x = hero` is the old rule: a copy if it is Copy, an ownership transfer if it is Move. `x: List[i32] = v.get(0)` asks for an owned value; a view is still rejected. Assigning to a reference variable rebinds the pointer (`w = other`); it cannot be rebound if it is `fixed`. Changing the pointee is written as `w.hp = 1` and works only with `lend`.

### The Single-Parameter Rule
There are no Rust-style `'a` names. `-> ref T` returns a shared `T*`, and `-> lend T` returns a `T*` with a single writer. All the `return`s in the body must come from the **same** `read` or `lend` parameter (`p`, `p.field`, `p.get(i)`, or a reference variable tied to that parameter). The parameter does not have to be the first one. If more than one is a candidate, the tie is written out:

```gg
fn pick(a: read Player, b: read Player) -> ref Player tied to b:
    return b
```

Heap-owning parameters are already implicitly `read`. Returning a `T*` from a by-value or `consume` parameter is a dangling pointer and a compile error. A `tied to` target cannot be a local owner.

While a reference is alive, its root cannot be moved, reassigned, or `lend`ed. `read` allows other reads; `lend` allows no other access while the holder is still in use. A reference tied to an owner in an inner scope cannot be written outward or returned. The reference itself cannot be `consume`d; what is handed over is the place that owns the value.

---

## 5. Deferred Execution (`defer`)

`defer` marks cleanup code that must run when a function or scope is left (whether by normal exit, `return`, `break`, `continue`, or a `?` error).

### 5.1 LIFO (Last In, First Out) Order
If there is more than one `defer`, they run in reverse order, as in Zig and Go:

```gg
fn main():
    print("Started")
    
    defer print("Cleanup 1 (defined first, runs last)")
    defer print("Cleanup 2 (defined second)")
    defer print("Cleanup 3 (defined last, runs first)")
    
    print("Working...")
```

Output:
```text
Started
Working...
Cleanup 3 (defined last, runs first)
Cleanup 2 (defined second)
Cleanup 1 (defined first, runs last)
```

### 5.2 Defer on Early Returns (`return`)
However the function ends, it does not exit without running the `defer`red statements:

```gg
fn process_file(status_code: i32):
    print("Resource opened")
    defer print("Resource closed safely!")
    
    if status_code < 0:
        print("Error detected, returning early...")
        return
        
    print("File processed successfully")
```

---

## 6. Practice: An Ownership and Resource Safety Example

```gg
# bank_account.gg
struct Account:
    id: i32
    balance: f64

fn deposit(acc: lend Account, amount: f64):
    acc.balance += amount

fn close_and_transfer(acc: consume Account, target: lend Account):
    defer print("Account", acc.id, "closed successfully.")
    target.balance += acc.balance
    # acc's ownership ends here

fn main():
    my_acc = Account{ id: 101, balance: 500.0 }
    savings = Account{ id: 202, balance: 1000.0 }
    
    deposit(my_acc, 250.0)
    print("After deposit:", my_acc.balance)  # 750.0
    
    close_and_transfer(my_acc, savings)
    print("Savings account:", savings.balance) # 1750.0
    
    # my_acc can no longer be used here!
```

---

## 🎯 Chapter Summary and Exercises

In this chapter you learned:
* `read`: safe read-only access.
* `lend`: update the variable in place (the variable cannot be `fixed`).
* `consume`: hand over ownership (the variable is moved and cannot be used again).
* Copy types are copied on the stack, Move types are moved by ownership transfer.
* Automatic `drop` cleans up heap resources.
* `defer` gives guaranteed cleanup in LIFO order when scopes are left.

### Try It Yourself:
1. Create a `Task` struct (`title: str`, `completed: bool`). Complete the task with a `complete(t: lend Task)` function. Then hand the task over with `archive(t: consume Task)`.
2. Use two separate `defer`s in one function and observe that a resource is started and then closed in guaranteed reverse order.

Next chapter: [Chapter 05: Data Structures and Tuples](05_Data_Structures_and_Tuples.md)!
