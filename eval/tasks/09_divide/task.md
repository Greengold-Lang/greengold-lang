# Division as a Result

```gg
fn divide(a: i32, b: i32) -> Result[i32, str]
```

Return `Ok` of the integer quotient when `b` is not zero. Return `Err` when `b` is zero. The tests use non-negative `a` and a positive `b`, plus the zero divisor.
