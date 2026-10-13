"""Stable diagnostic codes.

A code is never reused for a different rule. GG01xx syntax, GG02xx names and types,
GG03xx ownership and references, GG04xx everything else.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Rule:
    code: str
    slug: str
    category: str
    summary: str
    explanation: str
    # Field name -> type description. Empty when the rule carries no `details`.
    details: tuple[tuple[str, str], ...] = ()


def _r(code: str, slug: str, category: str, summary: str, explanation: str,
       details: tuple[tuple[str, str], ...] = ()) -> Rule:
    return Rule(code, slug, category, summary, explanation, details)


RULES: dict[str, Rule] = {
    r.slug: r for r in (
        _r("GG0101", "tab-character", "syntax",
           "A tab was used where spaces are required.",
           "Indentation is four spaces. A tab is a different character, so the block structure is ambiguous."),
        _r("GG0102", "slash-comment", "syntax",
           "`//` is not a comment.",
           "Comments start with `#`. `//` is two division operators, or a mistake."),
        _r("GG0103", "indent-multiple", "syntax",
           "Indentation is not a multiple of four spaces.",
           "Each nested block adds exactly four spaces. Any other width is a syntax error."),
        _r("GG0104", "indent-increase", "syntax",
           "Indentation jumped by more than one level.",
           "A block may indent by exactly four spaces relative to the line that opened it."),
        _r("GG0105", "indent-mismatch", "syntax",
           "Indentation does not match an outer block.",
           "A dedent must land on the column of some block that is still open."),
        _r("GG0106", "unexpected-indent", "syntax",
           "A line is indented but the previous line did not open a block.",
           "Indentation is only legal after a line that ends with `:`."),
        _r("GG0107", "unclosed-delimiter", "syntax",
           "A bracket was opened and never closed.",
           "Every `(`, `[`, and `{` needs its matching closer."),
        _r("GG0108", "extra-delimiter", "syntax",
           "A closing bracket has no matching opener.",
           "The closer does not pair with any bracket that is still open."),
        _r("GG0109", "mismatched-delimiter", "syntax",
           "A closing bracket closes a different kind of opener.",
           "Parentheses, brackets, and braces must nest in matching pairs."),
        _r("GG0110", "unterminated-string", "syntax",
           "A string literal is not closed.",
           "A `\"` or `\"\"\"` was opened and the file ended before its closer."),
        _r("GG0111", "unterminated-char", "syntax",
           "A character literal is not closed.",
           "A `'` was opened and the line ended before the closing `'`."),
        _r("GG0112", "empty-char", "syntax",
           "A character literal is empty.",
           "A char literal holds one character, written `'A'` or an escape such as `'\\n'`."),
        _r("GG0113", "multibyte-char", "syntax",
           "A character literal holds more than one byte.",
           "Char literals are a single byte. Multi-byte text belongs in a string."),
        _r("GG0114", "char-length", "syntax",
           "A character literal holds more than one character.",
           "Write one character, or one escape, between the quotes."),
        _r("GG0115", "bad-escape", "syntax",
           "An escape sequence is not recognized.",
           "The legal escapes are `\\n`, `\\t`, `\\r`, `\\\\`, `\\'`, `\\\"`, and `\\0` in char literals."),
        _r("GG0116", "bad-number", "syntax",
           "A numeric literal is malformed.",
           "Digits, an optional `0x` or `0b` prefix, and `_` separators are the whole of a number."),
        _r("GG0117", "unrecognized-character", "syntax",
           "A character is not part of the language.",
           "The lexer found a character that does not start a token."),
        _r("GG0118", "expected-token", "syntax",
           "The parser expected a different token.",
           "The grammar requires a specific token here. The message names it."),
        _r("GG0119", "else-if", "syntax",
           "`else if` is not a keyword.",
           "The keyword is `elif`. `else if` is two tokens and does not open a branch."),
        _r("GG0120", "consume-outside-parameter", "syntax",
           "`consume` was written outside a parameter.",
           "Ownership moves because the parameter is declared `consume`. The call is written `f(x)`."),
        _r("GG0121", "chained-comparison", "syntax",
           "Comparisons cannot be chained.",
           "`a < b < c` is rejected. Write `a < b and b < c`."),
        _r("GG0122", "top-level", "syntax",
           "This declaration is not allowed at the top level.",
           "A file contains structs, enums, features, impls, functions, constants, externs, and imports."),
        _r("GG0123", "bad-syntax", "syntax",
           "The source does not match the grammar.",
           "The parser could not accept this construct. The message names the rule that failed."),
        _r("GG0124", "empty-block", "syntax",
           "A block that must contain a statement is empty.",
           "An arm or a body needs at least one statement. An empty block is not a no-op."),
        _r("GG0125", "decl-indent", "syntax",
           "A declaration's body is not indented by four spaces.",
           "Fields, variants, and nested declarations sit four spaces in from the line that opened them."),
        _r("GG0126", "variant-parens", "syntax",
           "Parentheses were written on a variant that has no payload.",
           "A variant with no fields is written as `Name`, with no `()`."),
        _r("GG0127", "question-syntax", "syntax",
           "`?` is not attached to a whole expression.",
           "`?` follows one Result or Optional expression. It is not an infix operator."),
        _r("GG0128", "bad-defer", "syntax",
           "`defer` does not defer a call or an assignment.",
           "`defer` runs a call or an assignment when the block ends. Other expressions are not deferred."),
        _r("GG0129", "no-effect", "syntax",
           "An expression is used as a statement and does nothing.",
           "A statement must call, assign, or otherwise act. A bare value is discarded."),
        _r("GG0130", "break-outside", "syntax",
           "`break` appears outside a loop.",
           "`break` leaves the innermost `while` or `for`. There is no loop here."),
        _r("GG0131", "unsupported-syntax", "syntax",
           "This syntax is not part of the language.",
           "The tokens are recognizable, but the construct is rejected. The message names it."),
        _r("GG0134", "async-method", "syntax",
           "A method was written as `async fn`.",
           "Only a free function can be `async`. Write an `async fn` outside the `impl` that takes the value as "
           "a parameter."),
        _r("GG0132", "removed-var", "syntax",
           "`var` is no longer part of the language.",
           "Variables can be changed by default, so `var` is deleted. `fixed x = ...` declares a variable "
           "that never changes. A top-level value is a `const`."),
        _r("GG0133", "foreign-syntax", "syntax",
           "Syntax from another language.",
           "`&&`, `||`, `!`, `++`, `--`, `;`, `let`, and `def` come from other languages. Greengold writes "
           "`and`, `or`, `not`, `+= 1`, `-= 1`, one statement per line, `x = value`, and `fn`. The fix is "
           "always the same word, so `gg fix` (or saving in the editor) rewrites it for you."),

        _r("GG0201", "type-mismatch", "type",
           "A value's type is not the type that was required.",
           "Greengold does not convert between types implicitly. The expected type and the found type differ.",
           (("expected", "string"), ("found", "string"))),
        _r("GG0202", "unknown-type", "resolution",
           "A type name is not defined.",
           "The name is not a primitive, a struct, an enum, or a type parameter in scope.",
           (("name", "string"),)),
        _r("GG0203", "undefined-name", "resolution",
           "A name is not defined.",
           "No variable, constant, or function with this name is in scope.",
           (("name", "string"),)),
        _r("GG0204", "missing-main", "resolution",
           "The program has no `fn main():`.",
           "An executable needs `fn main():` with no parameters and no result."),
        _r("GG0205", "missing-return", "type",
           "A function that returns a value does not return on every path.",
           "Every path through the body must reach a `return` of the declared type."),
        _r("GG0206", "wrong-arity", "type",
           "A call passes the wrong number of arguments.",
           "The number of arguments must equal the number of parameters."),
        _r("GG0207", "unknown-field", "resolution",
           "A struct has no field with this name.",
           "Field names are the ones written in the struct declaration."),
        _r("GG0208", "unknown-method", "resolution",
           "A type has no method with this name.",
           "Methods are the functions declared for that type in an `impl` block."),
        _r("GG0209", "duplicate-name", "resolution",
           "A name is defined twice in the same scope.",
           "Functions, types, constants, fields, and local variables do not overload."),
        _r("GG0210", "reserved-name", "resolution",
           "A name is reserved by the language or the prelude.",
           "Built-in types, prelude functions, and keywords cannot be redefined."),
        _r("GG0211", "bad-condition", "type",
           "A condition is not a bool.",
           "`if`, `while`, and `require` conditions must have type `bool`."),
        _r("GG0212", "slice-stored", "type",
           "A slice was stored somewhere other than a parameter.",
           "`[]T` is a view. It may be a function parameter and may not be stored or returned."),
        _r("GG0213", "private-name", "resolution",
           "A name is private to its module.",
           "Put a `public` line above the function, type, constant, method, or field. Other files only see names under `public`."),
        _r("GG0405", "extern-restriction", "extern",
           "An extern signature uses a type the ABI does not allow.",
           "Extern functions take numbers, bool, `read`/`lend` structs, or pointers. They do not take `consume`, slices, or arrays."),
        _r("GG0214", "generic-args", "type",
           "A generic type was written with the wrong arguments.",
           "Generic types always take their type arguments explicitly."),
        _r("GG0215", "bad-constant", "type",
           "A constant expression is not a constant.",
           "A `const` may use literals, earlier constants, and arithmetic. It may not use variables or I/O."),
        _r("GG0216", "out-of-range", "type",
           "A constant does not fit in its type.",
           "The value is outside the range of the declared integer type or bounded integer."),
        _r("GG0217", "type-error", "type",
           "A type rule was broken.",
           "The value, signature, or declaration is not valid for its type. The message names the rule."),
        _r("GG0218", "unknown-variant", "resolution",
           "An enum has no variant with this name.",
           "Variant names are the ones written in the enum declaration."),
        _r("GG0219", "bad-operator", "type",
           "An operator was applied to a type that does not support it.",
           "Arithmetic, bitwise, and comparison operators accept the types named in the message."),
        _r("GG0220", "bad-range", "type",
           "A range or a bound is not valid.",
           "A range needs a non-zero step of the right signedness, and `max_value` needs an integer type."),
        _r("GG0221", "bad-iterator", "type",
           "`for` was applied to a type that cannot be iterated.",
           "`for .. in` accepts ranges and lists. Other types are not iterable."),
        _r("GG0222", "incomplete-match", "type",
           "A `match` does not cover every value.",
           "Every variant, or the whole integer/bool range, must be handled or caught by `_`."),
        _r("GG0223", "unreachable-pattern", "type",
           "A match arm can never be selected.",
           "An earlier arm already covers this value, or an arm follows `_`."),
        _r("GG0224", "bad-pattern", "type",
           "A pattern does not fit the value being matched.",
           "The pattern's enum, payload arity, or literal kind disagrees with the matched type."),
        _r("GG0225", "bad-match", "type",
           "`match` cannot be applied to this value.",
           "`match` accepts enums, integers, chars, bools, and strings. `match lend` needs an addressable place."),
        _r("GG0226", "question-type", "type",
           "`?` was applied to a value the function cannot unwrap.",
           "The operand must be a Result or Optional whose error type matches the function's return type."),
        _r("GG0227", "infinite-type", "type",
           "A type contains itself by value.",
           "A struct or enum that contains itself needs a pointer. By-value recursion has no finite size."),
        _r("GG0228", "generic-conflict", "type",
           "A generic declaration contradicts itself.",
           "Type arguments, default methods, and aliases must agree. Cycles and duplicate parameters are rejected."),
        _r("GG0229", "inference-failed", "type",
           "A type could not be inferred.",
           "Write the type arguments explicitly. The compiler will not guess when more than one type fits."),
        _r("GG0230", "unsatisfied-bound", "bounds",
           "A type does not satisfy a feature bound.",
           "The feature requires a capability the type does not have, such as `Ord` or `Float`."),
        _r("GG0231", "not-equatable", "type",
           "A type cannot be compared with `==`.",
           "Structs, enums, tuples, arrays, and lists compare field by field and element by element. A part "
           "that has no `==` (a function pointer, an OS handle, a union) stops that; the type can define its own `eq`."),
        _r("GG0232", "not-printable", "type",
           "A type cannot be printed.",
           "`print` accepts numbers, bool, chars, and strings. Match an enum before printing it."),
        _r("GG0233", "bad-conversion", "cast",
           "A conversion between these types is not allowed.",
           "Numeric types convert with `T(x)`. Other pairs have no conversion."),
        _r("GG0234", "missing-field", "type",
           "A struct literal omits a field.",
           "Every field of the struct must be written in the literal."),
        _r("GG0235", "empty-enum", "type",
           "An enum declares no variants.",
           "An enum needs at least one variant. There is no value of an empty enum."),
        _r("GG0236", "heap-layout", "type",
           "A heap-owning type was placed where only a copyable layout is allowed.",
           "Arrays and nested list elements cannot own heap values. Use one list of the element type."),
        _r("GG0237", "slice-position", "type",
           "A slice was written outside an argument.",
           "A slice expression is an argument to a `[]T` parameter. It is not stored, and strings are not sliced."),
        _r("GG0238", "if-value", "type",
           "An `if` expression has no `else`.",
           "An `if` used as a value must have an `else` of the same type."),
        _r("GG0239", "bad-declaration", "resolution",
           "A declaration uses a name in a role that name cannot have.",
           "A type name is not a function, `main` is not generic, and a variant needs its enum as a qualifier."),
        _r("GG0240", "builtin-signature", "type",
           "A built-in was called with the wrong arguments.",
           "`panic` takes one `str` or `string` message. `input` takes at most one argument."),
        _r("GG0241", "unknown-feature", "resolution",
           "A feature name is not defined.",
           "Feature bounds name a `feature` declaration in scope."),
        _r("GG0242", "bad-pointer", "type",
           "A pointer type or a dereference is not allowed.",
           "A pointer targets a number, bool, struct, `void`, or another pointer. `*void` is not read, and `null` needs a known pointer type."),
        _r("GG0244", "bad-format", "type",
           "A format spec in an f-string is malformed or does not fit the value.",
           "After `:` in `{x:spec}` comes `[[fill]align][+][#][0][width][.precision][type]`. A precision is for "
           "floats, `x`/`X`/`b`/`o` and `#` for integers, `+` and `0` for numbers.",
           (("format", "string"), ("type", "string"))),
        _r("GG0243", "not-hashable", "type",
           "A type cannot be hashed.",
           "`hash(x)` mixes the hashes of the fields, elements, or variant and payload. A float has no exact hash "
           "(0.0 and -0.0 are equal), and a function pointer or OS handle has none. Define `fn hash(self: Self) -> u64`."),

        _r("GG0301", "use-after-consume", "ownership",
           "A value was used after it was consumed.",
           "A value passed to a `consume` parameter moves into the callee. The caller no longer owns it.",
           (("value", "string"), ("state", "string"),
            ("consumed_at", "{line, column}"), ("used_at", "{line, column}"),
            ("callee", "string or null"), ("parameter", "string or null"))),
        _r("GG0302", "use-after-partial-move", "ownership",
           "A value was used after one of its fields was consumed.",
           "Moving a field consumes that path. The parent cannot be used as a whole while the field is gone.",
           (("value", "string"), ("field", "string"), ("state", "string"),
            ("consumed_at", "{line, column}"), ("used_at", "{line, column}"),
            ("callee", "string or null"), ("parameter", "string or null"))),
        _r("GG0303", "consume-in-loop", "ownership",
           "A value declared outside a loop is consumed on every iteration.",
           "The loop would move the same value more than once. Move it outside the loop, or declare it inside.",
           (("value", "string"), ("state", "string"), ("consumed_at", "{line, column}"))),
        _r("GG0304", "consume-of-copy", "ownership",
           "`consume` was written on a type that is copied.",
           "Numbers, bool, and arrays of numbers are copied. `consume` is only for values that have a single owner.",
           (("type", "string"), ("parameter", "string"))),
        _r("GG0305", "double-lend", "reference",
           "The same memory is lent twice in one call.",
           "`lend` is exclusive. Two `lend` arguments may not overlap.",
           (("left", "string"), ("right", "string"), ("modes", "list of string"))),
        _r("GG0306", "lend-while-consume", "ownership",
           "A value is lent and consumed in the same call.",
           "`lend` borrows the value. `consume` gives it away. Those cannot happen together.",
           (("left", "string"), ("right", "string"), ("modes", "list of string"))),
        _r("GG0307", "lend-while-read", "reference",
           "A value is lent and read in the same call.",
           "While a `lend` is active, no other `read` of that memory is allowed.",
           (("left", "string"), ("right", "string"), ("modes", "list of string"))),
        _r("GG0308", "lend-alias", "reference",
           "A `lend` overlaps another use of the same memory.",
           "`lend` must be the only access to that memory for the duration of the call.",
           (("left", "string"), ("right", "string"), ("modes", "list of string"))),
        _r("GG0309", "immutable-assign", "mutability",
           "An assignment targets an immutable place.",
           "Variables can be changed unless they are declared `fixed`. Parameters, loop counters, and `read` references cannot.",
           (("name", "string"), ("kind", "string"))),
        _r("GG0310", "lend-immutable", "mutability",
           "`lend` was requested for an immutable place.",
           "A `lend` parameter needs a variable that is not `fixed`, or a place that is already `lend`.",
           (("name", "string"), ("kind", "string"))),
        _r("GG0311", "mutating-method", "mutability",
           "A mutating method was called on an immutable value.",
           "A method whose receiver is `lend` writes through the receiver. The receiver cannot be `fixed`.",
           (("name", "string"), ("kind", "string"))),
        _r("GG0312", "move-of-borrow", "ownership",
           "A borrowed value was moved.",
           "A `read` or `lend` parameter is not owned by this function, so it cannot be `consume`d.",
           (("value", "string"), ("kind", "string"))),
        _r("GG0313", "cannot-move", "ownership",
           "This place cannot be moved.",
           "Views, slices, and array elements have no ownership to give away. Only a whole owned value can be consumed.",
           (("value", "string"),)),
        _r("GG0314", "partial-move", "ownership",
           "A heap-owning field was moved on its own.",
           "Heap-owning fields move with the whole value. Moving one field would leave the parent unable to free it.",
           (("value", "string"),)),
        _r("GG0315", "reference-escapes", "reference",
           "A reference would outlive the value it points at.",
           "A `read` or `lend` stored in a variable or returned from a function cannot point at something that dies first.",
           (("referent", "string"), ("holder", "string"))),
        _r("GG0316", "borrow-invalidated", "reference",
           "A stored reference was used after its referent changed.",
           "While a holder is still used, the value it is tied to cannot be moved, reassigned, or lent.",
           (("referent", "string"), ("holder", "string"), ("bond", "string"), ("event", "string"))),
        _r("GG0317", "bad-tied-to", "reference",
           "A `tied to` clause does not name a live owner.",
           "A parameter may be tied to another parameter. A field may only be tied to `self`.",
           (("name", "string"), ("tied_to", "string"))),
        _r("GG0318", "consume-self", "ownership",
           "`consume self` is not supported on methods.",
           "A method cannot take ownership of its receiver. Take the value as a `consume` parameter of a function instead."),
        _r("GG0319", "immutable-place", "mutability",
           "A place cannot be written or lent.",
           "The place is reached through a read-only reference, a read-only slice, or a binding declared `fixed`.",
           (("name", "string"),)),
        _r("GG0320", "ref-return", "reference",
           "A `ref` return is not tied to a single reference parameter.",
           "The returned place must be inside one `read` or `lend` parameter, and every path must use that same parameter."),
        _r("GG0321", "missing-tied-to", "reference",
           "A reference field has no `tied to` binding.",
           "A field that stores a reference must name the owner it is tied to."),
        _r("GG0322", "not-first-class", "reference",
           "A function was used as a value, but a parameter is a reference.",
           "Only functions whose parameters are owned or copied can be passed as values."),
        _r("GG0323", "handle-copy", "ownership",
           "An OS handle was copied or cloned.",
           "A thread, lock, condition, atomic, or channel of `std.thread` is the OS object itself. A copy would be "
           "a second, unrelated object, so these values are moved, never copied. Pass them as `read` or `lend`.",
           (("value", "string"), ("handle", "string"))),
        _r("GG0324", "drop-signature", "ownership",
           "A `drop` method has the wrong signature.",
           "A destructor is written `fn drop(self: lend Self)` inside `impl Type:`. It takes no other parameter "
           "and returns nothing. It runs once, when the value goes away, before the fields are freed."),
        _r("GG0325", "drop-misuse", "ownership",
           "A value with a destructor was used in a way that would skip or repeat `drop`.",
           "`drop` runs by itself at the end of the owner's scope. It cannot be called by hand, a value with "
           "`drop` cannot be cloned unless the type defines `clone`, and `match consume` cannot take its payload apart.",
           (("type", "string"),)),
        _r("GG0326", "not-send", "ownership",
           "A value that is not safe on another thread was passed to a `send` parameter.",
           "A `send` parameter hands its argument to another thread. The compiler infers whether that is safe: "
           "a view (`str`, a slice, a reference field), a raw pointer, or a value with a non-atomic owner count "
           "(`Shared`, a stored `Fn`) cannot cross. Send owned data (`string`, `List`), or share it with `Arc`.",
           (("value", "string"), ("reason", "string"))),
        _r("GG0327", "list-helper-moved", "ownership",
           "A list method that copies elements was called on a list of moved values.",
           "`map`, `filter`, `sort`, `contains` and the other list helpers hand each element to a callback or "
           "return it by value, so the elements must be copied. A list of `string`, `List`, or other owned values "
           "is walked with `for x in xs:` instead.",
           (("method", "string"), ("element", "string"))),

        _r("GG0328", "async-borrow-param", "ownership",
           "A parameter of an `async fn` is `read` or `lend`.",
           "Calling an `async fn` starts a task and returns at once; the task may run after the caller has moved "
           "on, so it cannot hold a borrow of the caller's value. Pass the value itself (it moves into the "
           "task), or an `Arc` to share it read-only."),

        _r("GG0401", "comptime-failed", "effect",
           "A constant could not be evaluated at compile time.",
           "`comptime fn` may compute numbers, arrays, and structs. It cannot perform I/O or allocate."),
        _r("GG0402", "missing-file", "other",
           "An imported file was not found.",
           "The import path does not name a file the compiler can read."),
        _r("GG0403", "read-failed", "other",
           "A source file could not be read.",
           "The operating system rejected the read. The message includes the system reason."),
        _r("GG0404", "compiler-internal", "other",
           "The compiler hit an internal error.",
           "This is a bug in the compiler, not in the program."),
        _r("GG0406", "unsafe-required", "effect",
           "This operation is only legal in `unsafe:`.",
           "Pointer calls and trusted indexing are explicit. The surrounding `unsafe:` block opts in. "
           "`hot fn` is only a performance hint and does not."),
        _r("GG0407", "unknown-attribute", "other",
           "An `@attribute` was used without being declared.",
           "An attribute has no meaning until `attribute name(params)` declares it. A misspelled name is an "
           "error, not a silent no-op."),
        _r("GG0408", "bad-attribute", "other",
           "An `@attribute` does not match its declaration.",
           "The arguments, their kinds, or the item it is written on differ from the `attribute` declaration."),
        _r("GG0499", "unclassified", "other",
           "This diagnostic has no specific code yet.",
           "The message is real, but it has not been given a stable rule. Treat the message text as the explanation."),
    )
}

BY_CODE: dict[str, Rule] = {r.code: r for r in RULES.values()}

# First match wins. Longer, more specific patterns come first.
_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(p), slug) for p, slug in (
        (r"parameter of an `async fn` cannot be", "async-borrow-param"),
        (r"A method cannot be `async`", "async-method"),
        (r"`consume` can only be used in a parameter", "consume-outside-parameter"),
        (r"cannot be used: field `[^`]*` was moved", "use-after-partial-move"),
        (r"was moved \(`consume`\)", "use-after-consume"),
        (r"each iteration of the loop", "consume-in-loop"),
        (r"is copied, `consume` is not needed", "consume-of-copy"),
        (r"cannot be borrowed as `lend` multiple times", "double-lend"),
        (r"cannot be borrowed as `lend` in the same call", "double-lend"),
        (r"while being moved \(`consume`\)", "lend-while-consume"),
        (r"both `read` and `lend`", "lend-while-read"),
        (r"aliasing risk", "lend-alias"),
        (r"you do not own it", "move-of-borrow"),
        (r"no partial moves", "partial-move"),
        (r"cannot be moved", "cannot-move"),
        (r"is a view \(`ref`\)", "cannot-move"),
        (r"does not live long enough", "reference-escapes"),
        (r"cannot be returned", "reference-escapes"),
        (r"still tied to it", "borrow-invalidated"),
        (r"no other access is permitted", "borrow-invalidated"),
        (r"cannot be tied to itself", "bad-tied-to"),
        (r"no parameter named", "bad-tied-to"),
        (r"can only be tied to `self`", "bad-tied-to"),
        (r"cannot be tied to a value parameter", "bad-tied-to"),
        (r"`consume self` is not yet supported", "consume-self"),
        (r"Cannot assign", "immutable-assign"),
        (r"Cannot rebind", "immutable-assign"),
        (r"cannot be `lend`ed", "lend-immutable"),
        (r"is a mutating method", "mutating-method"),
        (r"is immutable", "immutable-place"),
        (r"Tab characters are not allowed", "tab-character"),
        (r"// is not a comment", "slash-comment"),
        (r"Indentation must be a multiple", "indent-multiple"),
        (r"Indentation must increase", "indent-increase"),
        (r"Indentation does not match", "indent-mismatch"),
        (r"Unexpected indentation", "unexpected-indent"),
        (r"opened but never closed", "unclosed-delimiter"),
        (r"no matching open bracket", "extra-delimiter"),
        (r"closes wrong bracket", "mismatched-delimiter"),
        (r"Unterminated", "unterminated-string"),
        (r"Unclosed `\{`", "unterminated-string"),
        (r"Empty expression in formatted string", "bad-syntax"),
        (r"Empty char literal", "empty-char"),
        (r"multi-byte UTF-8", "multibyte-char"),
        (r"single character", "char-length"),
        (r"Unknown escape", "bad-escape"),
        (r"escape sequence can only be used in char", "bad-escape"),
        (r"Invalid hexadecimal|Invalid binary|Invalid number", "bad-number"),
        (r"Unrecognized character", "unrecognized-character"),
        (r"`else if` does not exist", "else-if"),
        (r"`var` was removed", "removed-var"),
        (r"is not Greengold syntax", "foreign-syntax"),
        (r"Chained comparison", "chained-comparison"),
        (r"can be declared at top-level|Only `struct`", "top-level"),
        (r"Type mismatch:", "type-mismatch"),
        (r"Unknown type `", "unknown-type"),
        (r"is not defined|No function named|No struct named|has no `", "undefined-name"),
        (r"is private", "private-name"),
        (r"Import name `|cannot import itself", "duplicate-name"),
        (r"`fn main` is only allowed", "bad-declaration"),
        (r"`fn main\(\):` not found", "missing-main"),
        (r"not all paths have a `return`|must return `", "missing-return"),
        (r"expects \d+ argument", "wrong-arity"),
        (r"has no field named", "unknown-field"),
        (r"has no method named", "unknown-method"),
        (r"has no variant named|is not a variant", "unknown-variant"),
        (r"already defined|defined twice|must be unique|conflicts with a function", "duplicate-name"),
        (r"reserved name|is a reserved", "reserved-name"),
        (r"Condition must be `bool`", "bad-condition"),
        (r"Slice \(`\[\]T`\) cannot|Slice cannot be stored|cannot be an arm value", "slice-stored"),
        (r"body is empty", "empty-block"),
        (r"must be indented", "decl-indent"),
        (r"pattern has|value must be provided|Pattern specifies", "bad-pattern"),
        (r"empty payload parentheses|do not write parentheses", "variant-parens"),
        (r"`\?` can only be used on the whole expression", "question-syntax"),
        (r"`defer` defers", "bad-defer"),
        (r"does not perform any action", "no-effect"),
        (r"`break` can only be used inside", "break-outside"),
        (r"heap-owning", "heap-layout"),
        (r"not supported|cannot have their own type parameters|cannot be an enum payload", "unsupported-syntax"),
        (r"Both sides of|can only be used with|only compares numbers|right operand|does not support operator|Unary `", "bad-operator"),
        (r"Tuples must have", "type-error"),
        (r"too small for|too large for|cannot be negative|bounded integer range", "out-of-range"),
        (r"`step` cannot be zero|Negative `step`|`max_value` requires", "bad-range"),
        (r"Cannot iterate over", "bad-iterator"),
        (r"does not cover all cases", "incomplete-match"),
        (r"unreachable |redundant `_`|duplicate arm", "unreachable-pattern"),
        (r"Literal/range patterns|`match` can only be used|`match lend`", "bad-match"),
        (r"Function using `\?`|`\?` can only be applied|`\?` cannot mix|`\?`: error types", "question-type"),
        (r"contains itself|cannot contain itself|infinite recursive", "infinite-type"),
        (r"Conflicting default|refers to itself|written twice|conflicts with an existing type", "generic-conflict"),
        (r"could not be inferred|inferred as both", "inference-failed"),
        (r"does not satisfy", "unsatisfied-bound"),
        (r"cannot be compared", "not-equatable"),
        (r"cannot be printed", "not-printable"),
        (r"cannot be hashed", "not-hashable"),
        (r"cannot be converted|conversion cannot", "bad-conversion"),
        (r"Missing field", "missing-field"),
        (r"has no variants", "empty-enum"),
        (r"Slice expression can only|cannot be sliced", "slice-position"),
        (r"cannot produce a value without `else`", "if-value"),
        (r"is a enum name|cannot be generic|qualifier is required|`main` takes no parameters", "bad-declaration"),
        (r"`panic` |`input` takes", "builtin-signature"),
        (r"`ref` return|`-> ref T`|Reference return", "ref-return"),
        (r"requires a `tied to`", "missing-tied-to"),
        (r"cannot be used as a function value", "not-first-class"),
        (r"does not return a value", "type-error"),
        (r"Unknown feature", "unknown-feature"),
        (r"pointer type for|can only point to|cannot be dereferenced", "bad-pointer"),
        (r"unsafe", "unsafe-required"),
        (r"extern", "extern-restriction"),
        (r"is a generic type|is not a generic|(?i:type argument)|must be written explicitly", "generic-args"),
        (r"constant|Cannot use `", "bad-constant"),
        (r"out of range|out of bounds|does not fit", "out-of-range"),
        (r"Imported file not found", "missing-file"),
        (r"Failed to read", "read-failed"),
        (r"Compiler internal error|LSP loop error|Handler error", "compiler-internal"),
        (r"comptime evaluation", "comptime-failed"),
        (r"Expected |expected ", "expected-token"),
        (r"opens a block, so it cannot follow|must contain at least one arm|body is empty", "expected-token"),
    )
]


def classify(message: str) -> tuple[Rule, dict]:
    """Map a diagnostic message to a rule. Explicit `rule=` at the call site wins over this."""
    for pattern, slug in _PATTERNS:
        if pattern.search(message):
            return RULES[slug], _extract(slug, message)
    return RULES["unclassified"], {}


def _extract(slug: str, message: str) -> dict:
    if slug == "type-mismatch":
        m = re.search(r"expected `([^`]*)`, found `([^`]*)`", message)
        if m:
            return {"expected": m.group(1), "found": m.group(2)}
    if slug in ("unknown-type", "undefined-name"):
        m = re.search(r"`([^`]+)`", message)
        if m:
            return {"name": m.group(1)}
    if slug == "consume-of-copy":
        m = re.search(r"^(\S+) is copied", message)
        if m:
            return {"type": m.group(1), "parameter": ""}
    return {}


def explain_text(code: str) -> str | None:
    rule = BY_CODE.get(code)
    if rule is None:
        return None
    lines = [f"{rule.code}  {rule.slug}", rule.category, "", rule.summary, "", rule.explanation]
    if rule.details:
        lines += ["", "details:"]
        lines += [f"  {name}: {typ}" for name, typ in rule.details]
    lines.append("")
    lines.append(f"gg explain {rule.code}")
    return "\n".join(lines) + "\n"


def explain_json(code: str) -> dict | None:
    rule = BY_CODE.get(code)
    if rule is None:
        return None
    return {
        "code": rule.code,
        "rule": rule.slug,
        "category": rule.category,
        "summary": rule.summary,
        "explanation": rule.explanation,
        "details": {name: typ for name, typ in rule.details},
    }


def error_codes_markdown() -> str:
    lines = [
        "# Greengold error codes",
        "",
        "Codes are stable. A code is never reused for a different rule.",
        "Bands: `GG01xx` syntax, `GG02xx` names and types, `GG03xx` ownership and references, `GG04xx` other.",
        "`gg explain <code>` prints the explanation. `gg explain <code> --json` prints the same fields as JSON.",
        "",
        "| Code | Rule | Category | Explanation |",
        "|---|---|---|---|",
    ]
    for rule in RULES.values():
        lines.append(f"| `{rule.code}` | `{rule.slug}` | {rule.category} | {rule.summary} |")
    lines.append("")
    lines.append("## Details")
    lines.append("")
    lines.append("Rules that carry `details` use the shape below. Other rules omit `details`.")
    lines.append("")
    for rule in RULES.values():
        if not rule.details:
            continue
        lines.append(f"### `{rule.code}` `{rule.slug}`")
        lines.append("")
        lines.append(rule.explanation)
        lines.append("")
        for name, typ in rule.details:
            lines.append(f"- `{name}`: {typ}")
        lines.append("")
    return "\n".join(lines)
