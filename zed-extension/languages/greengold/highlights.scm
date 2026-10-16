; Comments and literals
(comment) @comment
(string) @string
(character) @string
(escape_sequence) @string.escape
(integer) @number
(float) @number
(boolean) @boolean
(null) @constant.builtin
(self) @variable.special

; Keywords
[
  "fn" "struct" "enum" "union" "feature" "impl" "extern" "import"
  "if" "elif" "else" "then" "while" "for" "in" "match" "let"
  "return" "break" "continue" "pass" "defer" "await"
  "public" "private" "hot" "trust" "fixed" "const" "static"
  "unsafe" "comptime" "async" "consume" "lend" "test"
] @keyword

["and" "or" "not"] @keyword.operator

(operator) @operator
["(" ")" "[" "]" "{" "}"] @punctuation.bracket
["," ":" ";" "."] @punctuation.delimiter

; Declarations
(function_item name: (identifier) @function)
(type_item name: (identifier) @type)
(impl_item name: (identifier) @type)
(test_item name: (identifier) @function)
(import_item path: (identifier) @namespace)

; Calls and members
(call_expression function: (identifier) @function)
(method_call method: (identifier) @function.method)
(field_access field: (identifier) @property)

((call_expression function: (identifier) @function.builtin)
  (#any-of? @function.builtin
    "print" "eprint" "panic" "input" "addr" "addr_mut" "ptr_offset" "ptr_to_int"
    "int_to_ptr" "cstr_to_string" "string_to_cstr" "str_from_raw" "ptr_read" "ptr_write"
    "ptr_cast" "volatile_read" "volatile_write" "atomic_load" "atomic_store" "atomic_add"
    "atomic_sub" "atomic_and" "atomic_or" "atomic_xor" "atomic_swap" "atomic_cas" "fence"
    "size_of" "align_of" "add_overflows" "sub_overflows" "mul_overflows" "max_value"
    "min_value" "target_os" "target_arch" "hash" "asm" "wrapping_add" "wrapping_sub"
    "wrapping_mul" "saturating_add" "saturating_sub" "saturating_mul" "checked_add"
    "checked_sub" "checked_mul"))

; Types
((identifier) @type.builtin
  (#any-of? @type.builtin
    "i8" "i16" "i32" "i64" "isize" "u8" "u16" "u32" "u64" "usize" "f32" "f64"
    "int" "uint" "float" "double" "bool" "str" "void" "Self" "string"
    "f32x4" "f32x8" "f64x2" "f64x4" "i32x4" "i32x8" "i64x2" "i64x4" "i16x8" "u8x16" "u32x4"))

((identifier) @type
  (#match? @type "^[A-Z]"))

((identifier) @constant.builtin
  (#any-of? @constant.builtin "Valid" "None" "Ok" "Err"))

; Parameter modes and other contextual words
((identifier) @keyword
  (#any-of? @keyword
    "read" "send" "tied" "dyn" "soa" "exclusive" "weak" "packed" "align" "wrapping"
    "overflow" "wrap" "trap" "require" "allocator" "step" "copy"))

((identifier) @variable.special
  (#eq? @variable.special "_"))
