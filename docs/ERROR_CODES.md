# Greengold error codes

Codes are stable. A code is never reused for a different rule.
Bands: `GG01xx` syntax, `GG02xx` names and types, `GG03xx` ownership and references, `GG04xx` other.
`gg explain <code>` prints the explanation. `gg explain <code> --json` prints the same fields as JSON.

| Code | Rule | Category | Explanation |
|---|---|---|---|
| `GG0101` | `tab-character` | syntax | A tab was used where spaces are required. |
| `GG0102` | `slash-comment` | syntax | `//` is not a comment. |
| `GG0103` | `indent-multiple` | syntax | Indentation is not a multiple of four spaces. |
| `GG0104` | `indent-increase` | syntax | Indentation jumped by more than one level. |
| `GG0105` | `indent-mismatch` | syntax | Indentation does not match an outer block. |
| `GG0106` | `unexpected-indent` | syntax | A line is indented but the previous line did not open a block. |
| `GG0107` | `unclosed-delimiter` | syntax | A bracket was opened and never closed. |
| `GG0108` | `extra-delimiter` | syntax | A closing bracket has no matching opener. |
| `GG0109` | `mismatched-delimiter` | syntax | A closing bracket closes a different kind of opener. |
| `GG0110` | `unterminated-string` | syntax | A string literal is not closed. |
| `GG0111` | `unterminated-char` | syntax | A character literal is not closed. |
| `GG0112` | `empty-char` | syntax | A character literal is empty. |
| `GG0113` | `multibyte-char` | syntax | A character literal holds more than one byte. |
| `GG0114` | `char-length` | syntax | A character literal holds more than one character. |
| `GG0115` | `bad-escape` | syntax | An escape sequence is not recognized. |
| `GG0116` | `bad-number` | syntax | A numeric literal is malformed. |
| `GG0117` | `unrecognized-character` | syntax | A character is not part of the language. |
| `GG0118` | `expected-token` | syntax | The parser expected a different token. |
| `GG0119` | `else-if` | syntax | `else if` is not a keyword. |
| `GG0120` | `consume-outside-parameter` | syntax | `consume` was written outside a parameter. |
| `GG0121` | `chained-comparison` | syntax | Comparisons cannot be chained. |
| `GG0122` | `top-level` | syntax | This declaration is not allowed at the top level. |
| `GG0123` | `bad-syntax` | syntax | The source does not match the grammar. |
| `GG0124` | `empty-block` | syntax | A block that must contain a statement is empty. |
| `GG0125` | `decl-indent` | syntax | A declaration's body is not indented by four spaces. |
| `GG0126` | `variant-parens` | syntax | Parentheses were written on a variant that has no payload. |
| `GG0127` | `question-syntax` | syntax | `?` is not attached to a whole expression. |
| `GG0128` | `bad-defer` | syntax | `defer` does not defer a call or an assignment. |
| `GG0129` | `no-effect` | syntax | An expression is used as a statement and does nothing. |
| `GG0130` | `break-outside` | syntax | `break` appears outside a loop. |
| `GG0131` | `unsupported-syntax` | syntax | This syntax is not part of the language. |
| `GG0134` | `async-method` | syntax | A method was written as `async fn`. |
| `GG0132` | `removed-var` | syntax | `var` is no longer part of the language. |
| `GG0133` | `foreign-syntax` | syntax | Syntax from another language. |
| `GG0201` | `type-mismatch` | type | A value's type is not the type that was required. |
| `GG0202` | `unknown-type` | resolution | A type name is not defined. |
| `GG0203` | `undefined-name` | resolution | A name is not defined. |
| `GG0204` | `missing-main` | resolution | The program has no `fn main():`. |
| `GG0205` | `missing-return` | type | A function that returns a value does not return on every path. |
| `GG0206` | `wrong-arity` | type | A call passes the wrong number of arguments. |
| `GG0207` | `unknown-field` | resolution | A struct has no field with this name. |
| `GG0208` | `unknown-method` | resolution | A type has no method with this name. |
| `GG0209` | `duplicate-name` | resolution | A name is defined twice in the same scope. |
| `GG0210` | `reserved-name` | resolution | A name is reserved by the language or the prelude. |
| `GG0211` | `bad-condition` | type | A condition is not a bool. |
| `GG0212` | `slice-stored` | type | A slice was stored somewhere other than a parameter. |
| `GG0213` | `private-name` | resolution | A name is private to its module. |
| `GG0405` | `extern-restriction` | extern | An extern signature uses a type the ABI does not allow. |
| `GG0214` | `generic-args` | type | A generic type was written with the wrong arguments. |
| `GG0215` | `bad-constant` | type | A constant expression is not a constant. |
| `GG0216` | `out-of-range` | type | A constant does not fit in its type. |
| `GG0217` | `type-error` | type | A type rule was broken. |
| `GG0218` | `unknown-variant` | resolution | An enum has no variant with this name. |
| `GG0219` | `bad-operator` | type | An operator was applied to a type that does not support it. |
| `GG0220` | `bad-range` | type | A range or a bound is not valid. |
| `GG0221` | `bad-iterator` | type | `for` was applied to a type that cannot be iterated. |
| `GG0222` | `incomplete-match` | type | A `match` does not cover every value. |
| `GG0223` | `unreachable-pattern` | type | A match arm can never be selected. |
| `GG0224` | `bad-pattern` | type | A pattern does not fit the value being matched. |
| `GG0225` | `bad-match` | type | `match` cannot be applied to this value. |
| `GG0226` | `question-type` | type | `?` was applied to a value the function cannot unwrap. |
| `GG0227` | `infinite-type` | type | A type contains itself by value. |
| `GG0228` | `generic-conflict` | type | A generic declaration contradicts itself. |
| `GG0229` | `inference-failed` | type | A type could not be inferred. |
| `GG0230` | `unsatisfied-bound` | bounds | A type does not satisfy a feature bound. |
| `GG0231` | `not-equatable` | type | A type cannot be compared with `==`. |
| `GG0232` | `not-printable` | type | A type cannot be printed. |
| `GG0233` | `bad-conversion` | cast | A conversion between these types is not allowed. |
| `GG0234` | `missing-field` | type | A struct literal omits a field. |
| `GG0235` | `empty-enum` | type | An enum declares no variants. |
| `GG0236` | `heap-layout` | type | A heap-owning type was placed where only a copyable layout is allowed. |
| `GG0237` | `slice-position` | type | A slice was written outside an argument. |
| `GG0238` | `if-value` | type | An `if` expression has no `else`. |
| `GG0239` | `bad-declaration` | resolution | A declaration uses a name in a role that name cannot have. |
| `GG0240` | `builtin-signature` | type | A built-in was called with the wrong arguments. |
| `GG0241` | `unknown-feature` | resolution | A feature name is not defined. |
| `GG0242` | `bad-pointer` | type | A pointer type or a dereference is not allowed. |
| `GG0244` | `bad-format` | type | A format spec in an f-string is malformed or does not fit the value. |
| `GG0243` | `not-hashable` | type | A type cannot be hashed. |
| `GG0301` | `use-after-consume` | ownership | A value was used after it was consumed. |
| `GG0302` | `use-after-partial-move` | ownership | A value was used after one of its fields was consumed. |
| `GG0303` | `consume-in-loop` | ownership | A value declared outside a loop is consumed on every iteration. |
| `GG0304` | `consume-of-copy` | ownership | `consume` was written on a type that is copied. |
| `GG0305` | `double-lend` | reference | The same memory is lent twice in one call. |
| `GG0306` | `lend-while-consume` | ownership | A value is lent and consumed in the same call. |
| `GG0307` | `lend-while-read` | reference | A value is lent and read in the same call. |
| `GG0308` | `lend-alias` | reference | A `lend` overlaps another use of the same memory. |
| `GG0309` | `immutable-assign` | mutability | An assignment targets an immutable place. |
| `GG0310` | `lend-immutable` | mutability | `lend` was requested for an immutable place. |
| `GG0311` | `mutating-method` | mutability | A mutating method was called on an immutable value. |
| `GG0312` | `move-of-borrow` | ownership | A borrowed value was moved. |
| `GG0313` | `cannot-move` | ownership | This place cannot be moved. |
| `GG0314` | `partial-move` | ownership | A heap-owning field was moved on its own. |
| `GG0315` | `reference-escapes` | reference | A reference would outlive the value it points at. |
| `GG0316` | `borrow-invalidated` | reference | A stored reference was used after its referent changed. |
| `GG0317` | `bad-tied-to` | reference | A `tied to` clause does not name a live owner. |
| `GG0318` | `consume-self` | ownership | `consume self` is not supported on methods. |
| `GG0319` | `immutable-place` | mutability | A place cannot be written or lent. |
| `GG0320` | `ref-return` | reference | A `ref` return is not tied to a single reference parameter. |
| `GG0321` | `missing-tied-to` | reference | A reference field has no `tied to` binding. |
| `GG0322` | `not-first-class` | reference | A function was used as a value, but a parameter is a reference. |
| `GG0323` | `handle-copy` | ownership | An OS handle was copied or cloned. |
| `GG0324` | `drop-signature` | ownership | A `drop` method has the wrong signature. |
| `GG0325` | `drop-misuse` | ownership | A value with a destructor was used in a way that would skip or repeat `drop`. |
| `GG0326` | `not-send` | ownership | A value that is not safe on another thread was passed to a `send` parameter. |
| `GG0327` | `list-helper-moved` | ownership | A list method that copies elements was called on a list of moved values. |
| `GG0328` | `async-borrow-param` | ownership | A parameter of an `async fn` is `read` or `lend`. |
| `GG0401` | `comptime-failed` | effect | A constant could not be evaluated at compile time. |
| `GG0402` | `missing-file` | other | An imported file was not found. |
| `GG0403` | `read-failed` | other | A source file could not be read. |
| `GG0404` | `compiler-internal` | other | The compiler hit an internal error. |
| `GG0406` | `unsafe-required` | effect | This operation is only legal in `unsafe:`. |
| `GG0407` | `unknown-attribute` | other | An `@attribute` was used without being declared. |
| `GG0408` | `bad-attribute` | other | An `@attribute` does not match its declaration. |
| `GG0409` | `attribute-check` | other | The body of an `attribute` rejected this use. |
| `GG0410` | `attribute-print` | other | The body of an `attribute` printed this while compiling. |
| `GG0501` | `profile-unsafe` | profile | `unsafe:` is not allowed by the safety profile. |
| `GG0502` | `profile-panic` | profile | The safety profile does not allow code that stops the program on purpose. |
| `GG0503` | `profile-recursion` | profile | The safety profile does not allow recursion. |
| `GG0504` | `profile-heap` | profile | The safety profile does not allow the heap. |
| `GG0505` | `profile-unbounded-loop` | profile | The safety profile does not allow a `while` loop without a stated bound. |
| `GG0506` | `profile-mutable-static` | profile | The safety profile does not allow global mutable state. |
| `GG0507` | `profile-complexity` | profile | A function is more complex than the profile allows. |
| `GG0508` | `profile-long-function` | profile | A function is longer than the profile allows. |
| `GG0499` | `unclassified` | other | This diagnostic has no specific code yet. |

## Details

Rules that carry `details` use the shape below. Other rules omit `details`.

### `GG0201` `type-mismatch`

Greengold does not convert between types implicitly. The expected type and the found type differ.

- `expected`: string
- `found`: string

### `GG0202` `unknown-type`

The name is not a primitive, a struct, an enum, or a type parameter in scope.

- `name`: string

### `GG0203` `undefined-name`

No variable, constant, or function with this name is in scope.

- `name`: string

### `GG0244` `bad-format`

After `:` in `{x:spec}` comes `[[fill]align][+][#][0][width][.precision][type]`. A precision is for floats, `x`/`X`/`b`/`o` and `#` for integers, `+` and `0` for numbers.

- `format`: string
- `type`: string

### `GG0301` `use-after-consume`

A value passed to a `consume` parameter moves into the callee. The caller no longer owns it.

- `value`: string
- `state`: string
- `consumed_at`: {line, column}
- `used_at`: {line, column}
- `callee`: string or null
- `parameter`: string or null

### `GG0302` `use-after-partial-move`

Moving a field consumes that path. The parent cannot be used as a whole while the field is gone.

- `value`: string
- `field`: string
- `state`: string
- `consumed_at`: {line, column}
- `used_at`: {line, column}
- `callee`: string or null
- `parameter`: string or null

### `GG0303` `consume-in-loop`

The loop would move the same value more than once. Move it outside the loop, or declare it inside.

- `value`: string
- `state`: string
- `consumed_at`: {line, column}

### `GG0304` `consume-of-copy`

Numbers, bool, and arrays of numbers are copied. `consume` is only for values that have a single owner.

- `type`: string
- `parameter`: string

### `GG0305` `double-lend`

`lend` is exclusive. Two `lend` arguments may not overlap.

- `left`: string
- `right`: string
- `modes`: list of string

### `GG0306` `lend-while-consume`

`lend` borrows the value. `consume` gives it away. Those cannot happen together.

- `left`: string
- `right`: string
- `modes`: list of string

### `GG0307` `lend-while-read`

While a `lend` is active, no other `read` of that memory is allowed.

- `left`: string
- `right`: string
- `modes`: list of string

### `GG0308` `lend-alias`

`lend` must be the only access to that memory for the duration of the call.

- `left`: string
- `right`: string
- `modes`: list of string

### `GG0309` `immutable-assign`

Variables can be changed unless they are declared `fixed`. Parameters, loop counters, and `read` references cannot.

- `name`: string
- `kind`: string

### `GG0310` `lend-immutable`

A `lend` parameter needs a variable that is not `fixed`, or a place that is already `lend`.

- `name`: string
- `kind`: string

### `GG0311` `mutating-method`

A method whose receiver is `lend` writes through the receiver. The receiver cannot be `fixed`.

- `name`: string
- `kind`: string

### `GG0312` `move-of-borrow`

A `read` or `lend` parameter is not owned by this function, so it cannot be `consume`d.

- `value`: string
- `kind`: string

### `GG0313` `cannot-move`

Views, slices, and array elements have no ownership to give away. Only a whole owned value can be consumed.

- `value`: string

### `GG0314` `partial-move`

Heap-owning fields move with the whole value. Moving one field would leave the parent unable to free it.

- `value`: string

### `GG0315` `reference-escapes`

A `read` or `lend` stored in a variable or returned from a function cannot point at something that dies first.

- `referent`: string
- `holder`: string

### `GG0316` `borrow-invalidated`

While a holder is still used, the value it is tied to cannot be moved, reassigned, or lent.

- `referent`: string
- `holder`: string
- `bond`: string
- `event`: string

### `GG0317` `bad-tied-to`

A parameter may be tied to another parameter. A field may only be tied to `self`.

- `name`: string
- `tied_to`: string

### `GG0319` `immutable-place`

The place is reached through a read-only reference, a read-only slice, or a binding declared `fixed`.

- `name`: string

### `GG0323` `handle-copy`

A thread, lock, condition, atomic, or channel of `std.thread` is the OS object itself. A copy would be a second, unrelated object, so these values are moved, never copied. Pass them as `read` or `lend`.

- `value`: string
- `handle`: string

### `GG0325` `drop-misuse`

`drop` runs by itself at the end of the owner's scope. It cannot be called by hand, a value with `drop` cannot be cloned unless the type defines `clone`, and `match consume` cannot take its payload apart.

- `type`: string

### `GG0326` `not-send`

A `send` parameter hands its argument to another thread. The compiler infers whether that is safe: a view (`str`, a slice, a reference field), a raw pointer, or a value with a non-atomic owner count (`Shared`, a stored `Fn`) cannot cross. Send owned data (`string`, `List`), or share it with `Arc`.

- `value`: string
- `reason`: string

### `GG0327` `list-helper-moved`

`map`, `filter`, `sort`, `contains` and the other list helpers hand each element to a callback or return it by value, so the elements must be copied. A list of `string`, `List`, or other owned values is walked with `for x in xs:` instead.

- `method`: string
- `element`: string
