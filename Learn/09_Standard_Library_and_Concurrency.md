# Chapter 09: Standard Library and Concurrency

Greengold is not only a language syntax; it offers a rich standard library (`std.*`) ecosystem that meets modern needs such as the file system, dynamic collections, math, time, text processing, and concurrency (multithreading).

Standard library modules are imported by writing `import std.<module_name>` at the top of the file. Every file is a module. Imported names are valid only in that file and are qualified, as in `math.sqrt`. A file starts public. A lone `private` line closes the declarations under it to the outside; `public` opens them again.

---

## 1. Overview of the Standard Library Modules

| Module | Purpose | Notable functions / types |
|---|---|---|
| `std.fs` | File system and I/O | `fs.read_file_to_string`, `fs.write_string_to_file`, `fs.remove_file`, `fs.file_exists` |
| `std.string` | Advanced text manipulation | `string.str_contains`, `string.str_split`, `string.str_trim`, `string.parse_i64` |
| `std.collections` | Dynamic data structures | `collections.hashmap_new[str, i32]()`, `collections.hashset_new[i32]()` |
| `std.sort` | Sorting algorithms | `sort.sort`, `sort.sort_by`, `sort.binary_search` |
| `std.math` | Math functions and constants | `math.sqrt`, `math.sin`, `math.cos`, `math.pow`, `math.abs` |
| `std.rand` | Random number generation | `rand.rng_new`, `r.next_u64`, `r.below`, `r.range` |
| `std.time` | Time measurement and CPU ticks | `time.current_time`, `time.current_time_millis`, `time.clock_ticks` |
| `std.process` | Process management and environment variables | `process.process_exit`, `process.env_get` |
| `std.thread` | Concurrency and threads | `thread.Thread.spawn`, `thread.Mutex`, `thread.ChannelI64`, `thread.AtomicI64` |
| `std.mmio` | Hardware registers (volatile) | `mmio.reg32`, `set_bits`, `modify`, `Field`, `wait_bits_set` |
| `std.hal` | Driver interfaces shared by boards | `OutputPin`, `InputPin`, `I2c`, `SpiBus`, `Uart`, `Delay` |
| `std.dmath` | Math with identical bits on every machine | `dmath.exp`, `dmath.sin`, `dmath.pow`, `dmath.atan2` |
| `std.unicode` | Characters, case, width | `unicode.to_upper`, `unicode.width`, `unicode.grapheme_count` |
| `std.log` | Leveled log lines on stderr | `log.info`, `log.warn`, `log.kv`, `log.set_json` |
| `std.uuid` | RFC 9562 identifiers | `uuid.v4`, `uuid.v7`, `uuid.parse`, `uuid.format` |
| `std.csv` | CSV (RFC 4180) | `csv.parse`, `csv.format_row` |
| `std.toml` | TOML documents as a JSON tree | `toml.parse`, `toml.to_text` |
| `std.can` | CAN bus frames, CRC-15, J1939 | `can.CanFrame.data_frame`, `can.frame_crc15`, `can.j1939_id` |
| `std.money` | Money in minor units | `money.usd`, `plus`, `scaled`, `allocate` |
| `std.audit` | Tamper-evident append-only log | `audit.AuditLog.open`, `append`, `audit.verify` |
| `std.fix` | FIX trading messages | `fix.parse`, `FixBuilder`, `get`, `get_all` |
| `std.compress` | DEFLATE, zlib, gzip (with an output limit) | `compress.gzip_compress`, `compress.gzip_decompress` |

Each module starts with a comment block that shows its use; `gg api` lists every public name.

---

## 2. Dynamic Heap Collections: `List[T]` and `Box[T]`

`List[T]` and `Box[T]`, which are built into the compiler, allocate dynamic memory on the heap and are freed automatically at the end of the scope (`drop`).

### 2.1 Dynamic Array: `List[T]`
A dynamic array structure that grows automatically as elements are added:

```gg
fn main():
    names = List[str]()
    
    # Adding elements (.push):
    names.push("Ali")
    names.push("Veli")
    names.push("Ayse")
    
    print("List length:", names.len)  # 3
    print("First element:", names[0])        # Ali
    
    # Removing an element (.pop - returns an Optional):
    match names.pop():
        Valid(last):
            print("Last element removed:", last) # Ayse
        None:
            pass
            
    # Iterating with a loop:
    for name in names:
        print("Remaining:", name)
```

### 2.2 Heap Value: `Box[T]`
`Box` is used to keep a large data structure or a recursive structure behind a single pointer on the heap, instead of directly on the stack:

```gg
struct BigData:
    matrix: [1000]f64

fn main():
    # Allocate on the heap to prevent a stack overflow:
    boxed = Box[BigData](BigData{ matrix: [0.0; 1000] })
    boxed.value.matrix[0] = 42.0
    print("Heap data:", boxed.value.matrix[0])
```

---

## 3. Text Processing: `str` vs `string`

Text comes in two forms in Greengold:
1. **`str`:** A read-only, immutable memory slice that lives on the stack (`"hello"`).
2. **`string`:** A UTF-8 byte sequence that can grow dynamically on the heap (`std.string` / Prelude).

```gg
import std.string

fn main():
    # Creating a string that can grow on the heap:
    msg = string.from("Greengold")
    msg.append_str(" Language")
    msg.append_byte('!')
    
    # To print it, we take the read-only view with as_str():
    print(msg.as_str())  # Greengold Language!
    
    # std.string helper functions:
    text = "  apple,pear,banana  "
    trimmed = string.str_trim(text)
    print("Trimmed:", trimmed)
    
    if string.str_contains(trimmed, "pear"):
        print("Pear found!")
```

---

## 4. File System and Input/Output (`std.fs`)

Reading, writing, and deleting files are done independently of the operating system with the `std.fs` module:

```gg
import std.fs

fn main():
    path = "record.txt"
    content = "File writing test with Greengold.\nSecond line."
    
    # Writing a file:
    if fs.write_string_to_file(path, content):
        print("File written successfully:", path)
    else:
        print("File write error!")
        
    # Reading a file (returns Optional[string]):
    match fs.read_file_to_string(path):
        Valid(text):
            print("File contents:\n", text.as_str())
        None:
            print("The file could not be read or was not found!")
            
    # Checking that the file exists, and deleting it:
    if fs.file_exists(path):
        fs.remove_file(path)
        print("Test file cleaned up.")
```

---

## 5. Concurrency and Threads (`std.thread`)

So that you can make use of all the cores of the hardware, Greengold offers OS-level native threads and thread-safety tools.

### 5.1 Starting a Thread (`Thread.spawn`)

```gg
import std.thread

fn background_worker():
    for i in 0..3:
        print("[Thread]:", i)

fn main():
    print("Main thread started")
    
    # Start a new thread in the background (safe, needs no unsafe):
    t = thread.Thread.spawn(background_worker)
    
    # Wait for the thread to finish (join):
    t.join()
    print("All threads finished.")
```

### 5.2 Mutual Exclusion: `Mutex`
When several threads access the same memory area, a lock is used to prevent a data race:

```gg
import std.thread

# Shared lock
lock = thread.Mutex.new()
shared_counter = 0

fn worker_job():
    lock.lock()
    # Protected critical section:
    shared_counter += 1
    lock.unlock()
```

`Thread`, `Mutex`, `Cond`, `AtomicI64`, and `ChannelI64` are operating system objects: **they are moved, not copied**.
Writing `n = m` moves `m`; a second, independent lock is not created. `m.clone()` and `copy m` do not compile (GG0323).
To give a lock or a channel to another function, pass it as a `read`/`lend` parameter.

### 5.3 Safe Messaging: Channels (`Channel`)
Instead of communicating by sharing memory, sharing memory by communicating is the safest approach:

```gg
import std.thread

fn main():
    ch = thread.ChannelI64.new()
    
    # Sending and receiving a value
    ch.send(42)
    
    if let Valid(message) = ch.recv():
        print("Data from the channel:", message)  # 42
    ch.close()
```

---

## 6. Practice: A Performance Test

```gg
# benchmark_demo.gg
import std.time
import std.math

fn calculate_heavy_sum(limit: i64) -> f64:
    total = 0.0
    for i in 0..limit:
        total += math.sqrt(f64(i))
    return total

fn main():
    print("Calculation starting...")
    start_time = time.current_time_millis()
    
    result = calculate_heavy_sum(10_000_000)
    
    end_time = time.current_time_millis()
    duration = end_time - start_time
    
    print("Result:", result)
    print("Total time (ms):", duration)
```

---

## 🎯 Chapter Summary and Exercises

In this chapter you learned:
* Standard library modules (`std.*`) and how to use `import`.
* The dynamic heap collections `List[T]` and `Box[T]`.
* The difference between `str` and `string`, and text manipulation.
* Reading and writing files with `std.fs`.
* Concurrency based on threads, Mutex, and Channel with `std.thread`.

### Try It Yourself:
1. Use `std.fs` to create a file named `notes.txt`, write a few lines into it, then read it back and print it.
2. Create a `List[i32]`, add 10 random numbers (`std.rand`) to it, and sort it with `std.sort`.

Next is [Chapter 10: FFI, Raw Pointers, and Systems Programming](10_FFI_Unsafe_and_Systems_Programming.md), where we go down to the limits of the hardware!
