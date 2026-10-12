# Ring buffer

A fixed-capacity queue of `i32`. Old values are overwritten in the buffer only after they have been popped. A push into a full buffer fails and leaves the buffer unchanged.

```gg
struct Ring:
    data: List[i32]
    cap: usize
    head: usize
    len: usize

fn ring_new(cap: usize) -> Ring

fn ring_push(r: lend Ring, value: i32) -> bool

fn ring_pop(r: lend Ring) -> Optional[i32]
```

`cap` is at least 1. `ring_pop` on an empty buffer is `None`. The first successful push is the first value popped.
