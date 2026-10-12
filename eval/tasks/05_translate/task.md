# Update a struct through `lend`

```gg
struct Point:
    x: i32
    y: i32

fn translate(p: lend Point, dx: i32, dy: i32)
```

Add `dx` to `x` and `dy` to `y`. The caller's variable changes. `dx` and `dy` may be negative or zero.
