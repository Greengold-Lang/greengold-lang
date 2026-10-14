## Not in the catalog above

The catalog lists declarations that have source. These parts of the language have none: they are known to the compiler. The normative text is [SPEC.md](SPEC.md); this page gathers what a program or a tool can reach.

### Attributes

Declare an attribute once, then write `@name(args)` on an item:

```
attribute name(param: kind, other: kind = default) on fn, struct, field:
    <optional comptime body>
```

| Part | Allowed values |
|---|---|
| `kind` of a parameter | `str`, `int`, `float`, `bool`, `ident` (a bare name such as `server`) |
| `= value` | makes the parameter optional; the default must fit the kind |
| `on` | any of `fn` (a function or a method), `struct`, `field`; without `on`, anywhere |
| arguments | positional or `key=value`; literals or bare names, never expressions |
| repeats | an attribute may be written once per item |

An attribute can go on a `fn`, a method in an `impl`, a `struct`, or a struct field. Nothing else (enums, variants, parameters, local variables, modules) takes one.

#### What the body can read

The body is `comptime` code that runs while compiling, once for each use. It sees:

| Name | Type | Value |
|---|---|---|
| each parameter | `str` for `str` and `ident`, `i64` for `int`, `f64` for `float`, `bool` for `bool` | the argument, or its default |
| `target_kind` | `str` | `"fn"`, `"struct"`, or `"field"` |
| `target_name` | `str` | the function, struct, or field name |
| `target_owner` | `str` | the struct of a method or field; empty for a free function or a struct |
| `target_type` | `str` | the result type of a function, or the type of a field; empty for a struct and for a function with no result |

It can call `compile_error(message)` to reject the use; the error points at the `@name` line. It follows the rules of `comptime fn`: no I/O, no heap.

The body does **not** see: the fields of the struct it is on, the parameters of the function it is on, the function body, other attributes on the same item, or other items in the program. To act on those, read `gg attrs` from a tool.

#### What `gg attrs file.gg` writes

`{"attributes": [item, ...]}`, one item per attributed `fn`, `struct`, or field:

| Key | On | Meaning |
|---|---|---|
| `kind` | all | `"fn"`, `"struct"`, or `"field"` |
| `name` | all | the item's name |
| `attrs` | all | `[{"name": ..., "args": {parameter: value}}]`, defaults filled in, `ident` as a string, `int` as a number |
| `file`, `line` | all | where the item is |
| `owner` | methods and fields | the struct that holds it |
| `module` | items from an imported file | the module name |
| `params` | `fn` | `[{"name", "type", "mode"}]`; `mode` is `""`, `"read"`, `"lend"`, or `"consume"` |
| `returns` | `fn` | the result type, or `null` |
| `type` | `field` | the field's type |

A struct item does not list its fields; they appear as their own `field` items when they carry an attribute.

### Compiler intrinsics

| Name | Where | Meaning |
|---|---|---|
| `require cond` | statement | stops the program, or fails the test, when `cond` is false; shows both sides of a comparison |
| `compile_error(message)` | attribute body only | rejects the use of the attribute |
| `size_of[T]()`, `align_of[T]()` | anywhere | `usize`; no `unsafe:` needed |
| `ptr_read[T](p)`, `ptr_write[T](p, value)` | `unsafe:` | move a `T` out of or into raw memory; `p` must be `*mut` for `ptr_write` |
| `volatile_read[T](p)`, `volatile_write[T](p, value)` | `unsafe:` | access a number, `bool`, or pointer that hardware may change; never merged or removed |
| `atomic_load[T](p, order)`, `atomic_store[T](p, value, order)` | `unsafe:` | atomic access |
| `atomic_add`, `atomic_sub`, `atomic_and`, `atomic_or`, `atomic_xor`, `atomic_swap` `[T](p, value, order)` | `unsafe:` | return the value before |
| `atomic_cas[T](p, expected, new, order)` | `unsafe:` | stores `new` only when the value is `expected`; returns the value it found |
| `fence(order)` | `unsafe:` | memory fence |

`order` is a string literal: `"relaxed"`, `"acquire"`, `"release"`, `"acq_rel"`, or `"seq_cst"`. A load cannot be `"release"` or `"acq_rel"`; a store cannot be `"acquire"` or `"acq_rel"`. `std.thread.Atomic[T]` wraps them safely.

### Command-line output formats

| Command | Output |
|---|---|
| `gg api [--json]` | the catalog above: `module`, `name`, `kind`, `signature`, `description` |
| `gg attrs file.gg` | the attribute JSON above |
| `gg check file.gg --json` | diagnostics: `code`, `rule`, `message`, `span`, `labels`, `fixes` (schema: [gg-diagnostics.schema.json](gg-diagnostics.schema.json)) |
| `gg test --json` | `summary.passed`, `summary.failed`, one object per test (schema: [gg-test.schema.json](gg-test.schema.json)) |
| `gg explain GG0301` | one error code explained; all codes in [ERROR_CODES.md](ERROR_CODES.md) |
