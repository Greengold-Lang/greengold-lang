# Greengold v2 Grammar (EBNF)

This document defines the syntax and grammar rules of the Greengold (v2) compiler in Extended Backus-Naur Form (EBNF).

---

## 1. Lexical Structure

```ebnf
newline         = "\n" | "\r\n" ;
whitespace      = " " ;  (* Tab characters are disallowed *)
comment         = "#" , { all_characters - newline } ;

letter          = "a" ... "z" | "A" ... "Z" | "_" ;
digit           = "0" ... "9" ;
hex_digit       = digit | "a" ... "f" | "A" ... "F" ;
bin_digit       = "0" | "1" ;

ident           = letter , { letter | digit } ;

int_lit         = decimal_lit | hex_lit | bin_lit ;
decimal_lit     = digit , { digit | "_" } ;
hex_lit         = ( "0x" | "0X" ) , hex_digit , { hex_digit | "_" } ;
bin_lit         = ( "0b" | "0B" ) , bin_digit , { bin_digit | "_" } ;

float_lit       = digit , { digit } , "." , digit , { digit } ;

char_escape     = "\\n" | "\\t" | "\\r" | "\\\\" | "\\'" | "\\\"" | "\\0" ;
char_lit        = "'" , ( ( all_characters - ( "'" | "\\" | "\n" | "\t" ) ) | char_escape ) , "'" ;

str_escape      = "\\n" | "\\t" | "\\r" | "\\\\" | "\\'" | "\\\"" ;  (* \0 is disallowed in strings *)
str_lit         = '"' , { ( all_characters - ( '"' | "\\" | "\n" | "\t" ) ) | str_escape } , '"' ;

bool_lit        = "true" | "false" ;

(* Keywords: public private fn struct enum const extern import fixed if elif else while for in return break
   continue match pass consume read lend and or not true false unsafe. `?` is an operator. `own` is not a keyword.
   `var` is reserved: the parser reports it and asks to delete it (variables can be changed by default).
   `as` is not a keyword; it is read only at the end of `import` and `extern`.
   `null` is not a keyword; it is read as a pointer literal whose type is inferred from context.
   `public` and `private` each occupy a line of their own. Declarations below follow that line until the next one.
   The file starts public. *)
```

---

## 2. Program and Top-Level Declarations

```ebnf
program         = { newline | visibility } , { top_decl } , "EOF" ;
visibility      = ( "public" | "private" ) , newline ;

top_decl        = struct_decl
                | extern_struct_decl
                | enum_decl
                | impl_decl
                | func_decl
                | test_decl
                | const_decl
                | extern_decl
                | import_decl ;

(* Import. The three tails are mutually exclusive. The binding is the last path segment,
   unless `as` renames it or `{ ... }` imports individual public names. *)
import_decl     = "import" , import_path , [ import_tail ] , newline ;
import_path     = str_lit | ident , { "." , ident } ;
import_tail     = "as" , ident | "{" , ident , { "," , ident } , "}" ;

(* Type parameters: capitalized identifiers *)
type_params     = "[" , ident , { "," , ident } , "]" ;

(* Struct Declaration (can be generic) *)
struct_decl     = "struct" , ident , [ type_params ] , ":" , newline ,
                  "INDENT" , { visibility | field_decl } , "DEDENT" ;
field_decl      = ident , ":" , type_ref , newline ;

(* Enum Declaration (can be generic); variants carry positional payloads *)
enum_decl       = "enum" , ident , [ type_params ] , ":" , newline ,
                  "INDENT" , variant_decl , { variant_decl } , "DEDENT" ;
variant_decl    = ident , [ "(" , type_ref , { "," , type_ref } , ")" ] , newline ;

(* Implementation Block: methods on structs and enums must be defined inside `impl` blocks.
   - `impl Point:`
   - `impl Pair[A, B]:` *)
impl_decl       = "impl" , [ ident , "." ] , ident , [ type_params ] , ":" , newline ,
                  "INDENT" , { visibility | func_decl } , "DEDENT" ;

(* Function / Method Declaration.
   Top-level functions: `fn max[T](...)`, `fn add(a: i32, b: i32) -> i32`
   Methods are defined inside `impl` blocks: `impl Type: fn method(self, ...)`
   Direct method declarations of the form `fn Type.method(...)` are not supported. *)
func_decl       = "fn" , ident , [ type_params ] ,
                  "(" , [ param_list ] , ")" , [ "->" , type_ref ] , ":" , block ;

(* Test block. `test` is a name, recognized only in this position.
   `test:` attaches to the nearest function above it. `test name:` adds a label.
   The body is not called from `fn main`. *)
test_decl       = "test" , [ ident ] , ":" , block ;

(* Global Constant Declaration *)
const_decl      = "const" , ident , ( "=" , expr | ":" , type_ref , "=" , expr ) , newline ;

(* C-layout struct: fields must be numeric, bool, pointer, nested extern struct, or arrays thereof *)
extern_struct_decl = "extern" , struct_decl ;

(* Extern C Function Declaration (cannot be generic). `...`: variadic (requires at least one fixed parameter) *)
extern_decl     = "extern" , [ str_lit ] , "fn" , ident , "(" , [ extern_param_list , [ "," , "..." ] ] , ")" ,
                  [ "->" , type_ref ] , [ "as" , ident ] , newline ;

param_list      = param , { "," , param } ;
param           = ident , ":" , [ "consume" | "read" | "lend" ] , type_ref ;

extern_param_list = extern_param , { "," , extern_param } ;
extern_param    = ident , ":" , [ "consume" ] , type_ref ;
```

---

## 3. Types (Type References)

```ebnf
type_ref        = primitive_type
                | ident                       (* Struct or enum name, or type parameter *)
                | ident , "." , ident         (* Type in another module: combat.Hero *)
                | ident , type_args           (* Generic application: Pair[i32, f64] *)
                | ident , "." , ident , type_args
                | "[" , expr , "]" , type_ref (* Fixed-size array: [N]T *)
                | "[" , "]" , type_ref        (* Slice: []T (parameter only) *)
                | "*" , type_ref              (* Raw pointer, read-only: *T (FFI) *)
                | "*" , "mut" , type_ref      (* Raw pointer, mutable: *mut T (FFI); `*void` = C void* *)
                ;

type_args       = "[" , type_ref , { "," , type_ref } , "]" ;   (* Empty list disallowed *)

primitive_type  = "i8"  | "i16" | "i32" | "i64" | "isize"
                | "u8"  | "u16" | "u32" | "u64" | "usize"
                | "f32" | "f64" | "bool" | "string" ;
```

---

## 4. Blocks and Statements

```ebnf
block           = newline , "INDENT" , { stmt } , "DEDENT" ;

stmt            = var_decl
                | assign_stmt
                | if_stmt
                | while_stmt
                | for_stmt
                | for_in_stmt
                | match_stmt
                | return_stmt
                | break_stmt
                | continue_stmt
                | pass_stmt
                | unsafe_stmt
                | expr_stmt ;

(* Raw pointer operations (`p[i]`, addr, addr_mut, ptr_cast, ptr_offset, ptr_to_int, int_to_ptr,
   cstr_to_string, string_to_cstr) and calling pointer-taking/returning or variadic extern functions can only occur here. *)
unsafe_stmt     = "unsafe" , ":" , block ;

(* A variable can be changed: `x = 5`, `x: i32 = 5`. `fixed` forbids every change: `fixed x = 5`.
   A variable that nothing changes is treated as `fixed`. *)
var_decl        = [ "fixed" ] , ident , ( "=" , expr | ":" , type_ref , "=" , expr ) , newline ;

assign_stmt     = place , assign_op , expr , newline ;
place           = ident | postfix_expr ;   (* Name, field, or index; `?` only allowed with `=` (see section 6) *)
assign_op       = "=" | "+=" | "-=" | "*=" | "/=" | "%=" | "&=" | "|=" | "^=" | "<<=" | ">>=" ;

if_stmt         = "if" , expr , ":" , block ,
                  { "elif" , expr , ":" , block } ,
                  [ "else" , ":" , block ] ;

while_stmt      = "while" , expr , ":" , block ;

for_stmt        = "for" , ident , "in" , expr , ( ".." | "..=" ) , expr ,
                  [ "step" , [ "-" ] , int_lit ] , ":" , block ;     (* `step` is a contextual keyword *)

(* expr is an integer (count 0..expr), array, slice, list or string.
   When the body changes the loop variable, it lends the element; `k, x` also binds the usize index. *)
for_in_stmt     = "for" , ident , [ "," , ident ] , "in" , expr , ":" , block ;

(* `match` is a statement. Modes match parameter modes:
   read (default), `lend` (in-place mutation), `consume` (scrutinee moved). *)
match_stmt      = "match" , [ "consume" | "lend" ] , expr , ":" , newline ,
                  "INDENT" , match_arm , { match_arm } , "DEDENT" ;
match_arm       = pattern , ":" , newline , [ "INDENT" , { stmt } , "DEDENT" ] ;
pattern         = "_"                                            (* Wildcard catch-all *)
                | [ ident , "." ] , ident , [ "(" , binding , { "," , binding } , ")" ]
                | scalar_pat , { "|" , scalar_pat } ;            (* integer / char / bool / string scrutinee *)
scalar_pat      = literal | literal , ( ".." | "..=" ) , literal ; (* ranges: integers and chars only *)
binding         = ident | "_" ;                                  (* Bare identifier in pattern = variant *)

return_stmt     = "return" , [ expr ] , newline ;

break_stmt      = "break" , newline ;

continue_stmt   = "continue" , newline ;

pass_stmt       = "pass" , newline ;

expr_stmt       = call_expr , newline                         (* Call only, or *)
                | try_expr , newline ;                        (* `f()?` whose return value is discarded *)
```

Note: The parser raises an error if an arm body is empty (header only); write `pass` for an empty body.

---

## 5. Expressions & Precedence

Operators in order of precedence (from lowest to highest):

```ebnf
expr            = or_expr ;

or_expr         = and_expr , { "or" , and_expr } ;

and_expr        = not_expr , { "and" , not_expr } ;

not_expr        = [ "not" ] , cmp_expr ;

cmp_expr        = bitor_expr , [ cmp_op , bitor_expr ] ;  (* Chained comparisons disallowed *)
cmp_op          = "==" | "!=" | "<" | "<=" | ">" | ">=" ;

bitor_expr      = bitxor_expr , { "|" , bitxor_expr } ;

bitxor_expr     = bitand_expr , { "^" , bitand_expr } ;

bitand_expr     = shift_expr , { "&" , shift_expr } ;

shift_expr      = add_expr , { ( "<<" | ">>" ) , add_expr } ;

add_expr        = mul_expr , { ( "+" | "-" ) , mul_expr } ;

mul_expr        = unary_expr , { ( "*" | "/" | "%" ) , unary_expr } ;

unary_expr      = ( "-" | "~" ) , unary_expr
                | postfix_expr ;

postfix_expr    = primary_expr , { method_suffix | field_suffix | index_suffix | try_suffix } ;

method_suffix   = "." , ident , "(" , [ arg_list ] , ")" ;
field_suffix    = "." , ident ;
index_suffix    = "[" , ( expr | slice_range ) , "]" ;
try_suffix      = "?" ;                      (* Type checker permits only at "full expression" positions *)

slice_range     = [ expr ] , ".." , [ expr ]
                | [ expr ] , "..=" , expr ;

arg_list        = arg , { "," , arg } ;
arg             = expr ;   (* the parameter's mode decides; the call does not repeat it *)

primary_expr    = int_lit
                | float_lit
                | char_lit
                | str_lit
                | bool_lit
                | call_expr
                | generic_call
                | struct_lit
                | type_app
                | ident
                | array_lit
                | cast_expr
                | "(" , expr , ")" ;

call_expr       = ident , "(" , [ arg_list ] , ")" ;

cast_expr       = numeric_type , "(" , expr , ")" ;

struct_lit      = ident , [ type_args ] , "{" , [ field_init_list ] , "}" ;
field_init_list = field_init , { ( "," | newline ) , field_init } , [ "," | newline ] ;
field_init      = ident , ":" , expr ;

array_lit       = "[" , [ expr_list | expr , ";" , expr ] , "]" ;
expr_list       = expr , { "," , expr } , [ "," ] ;

(* `ident [ ... ]` disambiguation. The parser decides as follows:
   1. If there is a top-level comma inside brackets OR `]` is followed by `(` or `{`,
      the content represents type arguments: generic_call, generic struct_lit, or type_app.
   2. Otherwise, index/slice is attempted (`a[i]`, `a[1..3]`); if the content can also be read as a type
      (e.g., `Optional[i32].None`), the second interpretation is preserved and disambiguated during type checking
      (variable name -> indexing, generic enum name -> type application). *)
generic_call    = ident , type_args , "(" , [ arg_list ] , ")" ;     (* max[i64](5, 2) *)
type_app        = ident , type_args ;                                (* Preceding `.Variant` only: Optional[i32].None *)
numeric_type    = "i8" | "i16" | "i32" | "i64" | "isize"
                | "u8" | "u16" | "u32" | "u64" | "usize" | "f32" | "f64"
                | "int" | "uint" | "float" | "double" ;  (* Type aliases: int=i32, uint=u32, float=f32, double=f64 *)
```

Semantic notes (not part of grammar, enforced during type checking):

* Variant constructions of the form `Shape.Circle(1.0)` and `Shape.Empty` are syntactically `method_suffix`/`field_suffix`; if the name is an enum, the type checker treats it as a constructor.
* Short constructors `Some(x)`, `None`, `Ok(x)`, `Err(e)` are standard `call_expr`/`ident`; the type checker resolves them to `Optional`/`Result` constructors.

---

## 6. `?` Positions (Type Checker Rule)

`try_suffix` can syntactically appear on any `postfix_expr`, but the type checker only permits it when `f()?` is the **entire** expression in the following positions:

```ebnf
try_position    = var_decl   (* x = f()?   ,  x: T = f()?       *)
                | assign_stmt (* x = f()?     (with `=` only)    *)
                | return_stmt (* return f()?                      *)
                | expr_stmt ; (* f()?                              *)
```

Any other position (`g(f()?)`, `f()? + 1`, `x += f()?`, conditionals) results in a compile error: "`?` can only be used as the entire expression".

## v4 additions

```ebnf
tuple_type   = '(' type ',' type {',' type} ')'            (* desugars to Tuple2..Tuple6 *)
fn_type      = 'fn' '(' [type {',' type}] ')' ['->' type]
lambda       = 'fn' '(' params ')' ['->' type] '=>' expr   (* no captures; lifted to a top-level fn *)
impl_block   = 'impl' [Name '.'] Name [type_params] ':' NEWLINE INDENT {func_decl} DEDENT
type_alias   = 'type' Name '=' type
destructure  = ['fixed'] name {',' name} '=' expr             (* '_' skips an element *)
if_let       = 'if' 'let' pattern '=' expr ':' block ['else' ':' block]
while_let    = 'while' 'let' pattern '=' expr ':' block
```
