# Stack

A stack of `i32` stored in a `List`. Pushing and popping borrow the stack. Consuming it yields only the count; the caller cannot use the stack after that call.

```gg
struct Stack:
    items: List[i32]

fn stack_new() -> Stack

fn stack_push(s: lend Stack, value: i32)

fn stack_pop(s: lend Stack) -> Optional[i32]

fn stack_len(s: read Stack) -> usize

fn stack_into_len(s: consume Stack) -> usize
```

`stack_new` is empty. `stack_pop` on an empty stack is `None`. `stack_pop` returns the most recently pushed value. `stack_len` and `stack_into_len` both return how many values are stored.
