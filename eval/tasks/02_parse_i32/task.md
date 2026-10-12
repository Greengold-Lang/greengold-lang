# Parse a decimal integer

```gg
fn parse_i32(text: str) -> Optional[i32]
```

Accept an optional leading `-` and then one or more digits. Return `None` for an empty string, a lone `-`, a leading `+`, or any other byte. The numbers in the tests fit in `i32`. Do not import `std.string`.
