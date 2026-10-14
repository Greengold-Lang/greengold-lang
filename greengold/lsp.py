"""Language Server Protocol (LSP 3.x) for Greengold Language.

This module runs using pure Python standard library (JSON-RPC 2.0 stdio) without any external
third-party package dependencies. It provides the following capabilities to VS Code and other LSP-compliant editors:
  1. Real-time Syntax and Type Diagnostics: Tokenizer, Parser, Typechecker, and MoveAnalyzer diagnostics.
  2. Hover Tooltips: Keywords, primitive types, prelude, function signatures, struct/enum fields.
     Inlay hints: inferred `read`/`lend`/`consume` modes, inferred `fixed`, and types left out of the source.
  3. Go to Definition: F12 / Ctrl+Click jump to function, struct, enum, variable, parameter, or import targets.
  4. Document Symbols / Outline: VS Code Outline, breadcrumbs, and Ctrl+Shift+O support.
  5. Code Completion: Keywords, types, in-scope variables, dot (.) member/method completions.
  6. Document Formatting: Standard 4-space indentation, operator spacing, and cleanup.
  7. Signature Help: Parameter hints and active parameter highlights in function calls.
  8. Code Actions: every compiler fix is a quick fix (the light bulb); `source.fixAll.greengold` applies
     every verified `safe` fix, so `editor.codeActionsOnSave` can repair a file on save.
"""
from __future__ import annotations

import json
import logging
import os
import re
import sys
import traceback
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from .ast_nodes import (
    Binding, BorrowExpr, ConstDecl, Defer, EnumDecl, Expr, ExternFuncDecl, FieldDecl,
    For, ForIn, FuncDecl, If, ImportDecl, Match, MatchArm, Node, Param,
    Program, Stmt, StructDecl, FeatureDecl, TypeRef, VarDecl, VariantDecl, While,
    Wrapping,
)
from .cli import _resolve_import_target, analyze, fix_source, load_sources_and_ast, verify_fixes
from .diagnostics import DiagnosticBag
from .lexer import KEYWORDS, Token, tokenize
from .parser import parse
from .typecheck import check_program, MoveAnalyzer
from .typeinfo import BUILTINS, ERR, PRELUDE_NAMES, PRIMS


# --- LSP Sabitleri -----------------------------------------------------------

class DiagnosticSeverity:
    Error = 1
    Warning = 2
    Information = 3
    Hint = 4


class InlayHintKind:
    Type = 1
    Parameter = 2


class SymbolKind:
    File = 1
    Module = 2
    Namespace = 3
    Package = 4
    Class = 5
    Method = 6
    Property = 7
    Field = 8
    Constructor = 9
    Enum = 10
    Interface = 11
    Function = 12
    Variable = 13
    Constant = 14
    String = 15
    Number = 16
    Boolean = 17
    Array = 18
    Object = 19
    Key = 20
    Null = 21
    EnumMember = 22
    Struct = 23
    Event = 24
    Operator = 25
    TypeParameter = 26


class CompletionItemKind:
    Text = 1
    Method = 2
    Function = 3
    Constructor = 4
    Field = 5
    Variable = 6
    Class = 7
    Interface = 8
    Module = 9
    Property = 10
    Unit = 11
    Value = 12
    Enum = 13
    Keyword = 14
    Snippet = 15
    Color = 16
    File = 17
    Reference = 18
    Folder = 19
    EnumMember = 20
    Constant = 21
    Struct = 22
    Event = 23
    Operator = 24
    TypeParameter = 25


class InsertTextFormat:
    PlainText = 1
    Snippet = 2


# --- Documentation Database -----------------------------------------------

KEYWORD_DOCS = {
    "fn": "**fn** (Function Declaration)\n\nDeclares a function or method.\n```gg\nfn add(a: i32, b: i32) -> i32:\n    return a + b\n\nimpl Player:\n    fn take_damage(self: lend Player, points: i32):\n        self.health -= points\n```",
    "struct": "**struct** (Struct Declaration)\n\nDeclares a user-defined data structure.\n```gg\nstruct Point:\n    x: i32\n    y: i32\n```",
    "enum": "**enum** (Algebraic Data Type Declaration)\n\nDefines tagged union / ADT. Variants can hold data or be unit.\n```gg\nenum Shape:\n    Circle(f64)\n    Rect(f64, f64)\n    Empty\n```",
    "feature": "**feature** (Feature Declaration)\n\nDefines a set of method signatures and default implementations providing shared behavior.\n```gg\nfeature Shape:\n    fn area(self: Self) -> f64\n    fn double_area(self: Self) -> f64:\n        return 2.0 * self.area()\n```",
    "consume": "**consume** (Ownership)\n\nTakes ownership of value via parameter or `match consume`; automatically `drop`ped at end of scope. Value is moved at call site and source variable can no longer be used. No special keyword needed at call site: `eat(box)`.\n```gg\nfn eat(k: consume Box):\n    print(k.value)\n```",
    "read": "**read** (Shared Read)\n\nUnlimited number of concurrent, read-only accesses. Ownership is not transferred; value cannot be mutated while `read` is active.\n```gg\nfn show(p: read Player):\n    print(p.health)\n```",
    "lend": "**lend** (Exclusive Mutable Borrow)\n\nSingle exclusive mutable access: cannot coexist with other `read`/`lend` borrows. Ownership is not transferred.\n```gg\nfn heal(p: lend Player):\n    p.health += 10\n```",
    "tied": "**tied to** (Lifetime Bond)\n\nSpecifies which value a reference field / parameter cannot outlive.\n```gg\nstruct View:\n    owner: read Player tied to self\n```",
    "async": "**async fn** (Task)\n\nCalling an `async fn` starts its body as a task (std.tasks) and returns a `Task[T]` at once; the arguments move into the task.\n```gg\nasync fn fetch(n: i32) -> i32:\n    tasks.sleep(10)\n    return n * 2\n```",
    "await": "**await** (Wait for a task)\n\n`await t` waits for task `t` while the other tasks run, and returns its result.\n```gg\nprint(await fetch(1) + await fetch(2))\n```",
    "comptime": "**comptime** (Compile Time)\n\n`comptime fn` is evaluated during compilation; result is embedded into the binary as a constant.\n```gg\ncomptime fn square(n: i32) -> i32:\n    return n * n\n\nconst K = square(12)\n```",
    "copy": "**copy** (Explicit Copy)\n\nExplicitly copies a copyable value: `b = copy a`.",
    "soa": "**soa** (Struct of Arrays)\n\nStores an array of structs as separate contiguous arrays per field (SIMD-friendly).\n```gg\nps = soa Array[Particle, 1024]\n```",
    "exclusive": "**exclusive** (Noalias Access)\n\nDeclares that a `read`/`lend` parameter does not alias any other name (LLVM `noalias`); loops are vectorized.\n```gg\nfn scale(v: exclusive lend []f32, k: f32):\n    for i in 0..v.len:\n        v[i] = v[i] * k\n```",
    "match": "**match** (Pattern Matching)\n\nPerforms exhaustive pattern matching on enums, integers, chars, booleans, and strings.\n```gg\nmatch x:\n    1 | 2:\n        print(\"one or two\")\n    3..=9:\n        print(\"small\")\n    _:\n        print(\"other\")\n```\nExpression form with `=>`:\n```gg\nlabel = match cmd:\n    \"quit\" => \"bye\"\n    _ => \"unknown\"\n```",
    "defer": "**defer** (Scope Exit Cleanup)\n\nExecuted in reverse order (LIFO) when enclosing block or function exits (including return, break, continue, or `?`).\n```gg\ndefer cleanup()\n```",
    "var": "**var** (removed)\n\nVariables can be changed by default, so `var` is no longer written. Delete it: `counter = 0`.",
    "fixed": "**fixed** (Variable That Never Changes)\n\nA variable can be changed by default. `fixed` forbids any change: assigning it, lending it, or calling a method that changes it is an error.\nA variable that is never changed is treated as `fixed` automatically; the editor shows that as a hint.\n```gg\nfixed limit = 10\ncount = 0\ncount += 1\n```",
    "const": "**const** (Constant Declaration)\n\nDeclares a compile-time constant.\n```gg\nconst MAX_SIZE: usize = 1024\nconst PI = 3.14159\n```",
    "extern": "**extern** (C Function / Struct Declaration)\n\nBinds external C library functions or C-layout structs.\n```gg\nextern \"math.h\" fn sqrt(x: f64) -> f64 as c_sqrt\nextern \"stdio.h\" fn printf(fmt: str, ...) -> i32 as c_printf\nextern struct CPoint:\n    x: i32\n    y: i32\n```",
    "import": "**import** (Module Import)\n\nBinds another file in this file only. The name is the last path segment, unless `as` renames it. `{ ... }` brings public names in unqualified. Imports are not re-exported.\n```gg\nimport std.math\nimport std.math as m\nimport std.math { sqrt, sin }\nimport \"types.gg\"\n```",
    "public": "**public** (Visibility Section)\n\nA line by itself. Every declaration below it is visible to other modules until a `private` line.\n```gg\npublic\nfn sqrt(x: f64) -> f64:\n    return x\n```",
    "private": "**private** (Visibility Section)\n\nA line by itself. Every declaration below it stays in this file until a `public` line. A file starts public.\n```gg\nprivate\nfn helper() -> i32:\n    return 1\n```",
    "test": "**test** (Test Block)\n\n`gg test` runs the block. `fn main` does not. `test:` belongs to the nearest function above it. `test name:` adds a label. `require` fails the test when the condition is false. `fn test_name():` with no parameters is also a test.\n```gg\nfn add(a: i32, b: i32) -> i32:\n    return a + b\n\ntest negatives:\n    require add(-1, 1) == 0\n```",
    "require": "**require** (Check)\n\nStops the program, or fails the current test, when the condition is false.\n```gg\nrequire n == 3\n```",
    "hot": "**hot** (Optimizer Hint)\n\n`hot fn` tells the optimizer this function is called often.\n```gg\nhot fn inner(x: i32) -> i32:\n    return x + 1\n```",
    "trust": "**trust** (Unchecked Index)\n\n`trust place[i]` skips the bounds check. It is legal only inside `unsafe:`.\n```gg\nunsafe:\n    return trust xs[0]\n```",
    "if": "**if** (Conditional Statement)\n\nExecutes code block based on a boolean condition.",
    "elif": "**elif** (Additional Conditional Statement)\n\nTests alternative condition when preceding if/elif condition is false.",
    "else": "**else** (Fallback Statement)\n\nBlock to execute when no condition is satisfied.",
    "while": "**while** (While Loop)\n\nRepeats block as long as condition is true.",
    "for": "**for** (Range, Count, or Collection Loop)\n\nLoops over a range (`0..n`, `0..=n` with optional `step`), count (`n`), or elements of a collection.\n```gg\nfor i in 10:               # 0..10\n    print(i)\nfor i in 0..=9 step 3:     # 0, 3, 6, 9\n    print(i)\nfor k, x in nums:          # index and element\n    print(k, x)\nfor e in ents:             # changing e lends each element\n    e.hp += 10\n```",
    "in": "**in** (Loop Operator)\n\nSpecifies range or collection in `for` loops.",
    "step": "**step** (Loop Stride)\n\nSpecifies step stride in range loops. Can be a positive or negative integer literal or expression.\n```gg\nfor i in 0..10 step 2:\n    print(i)\nfor i in 10..0 step -2:\n    print(i)\nfor i in range(n) step stride:\n    print(i)\n```",
    "range": "**range** (Count Loop)\n\n`for i in range(n):` is the same as `for i in n:`. `range` is a function call.\n```gg\nfor i in range(items.len):\n    print(items[i])\n```",
    "overflow": "**overflow** (Integer Overflow Mode)\n\nSets how `+`, `-`, and `*` behave for the rest of the function. `wrap` is two's-complement modular arithmetic. `trap` keeps the checked overflow trap (the default).\n```gg\nfn mix(x: u64) -> u64:\n    overflow: wrap\n    return x * 1000000007 + 123456789\n```\nThe same clause may sit on the signature, before the block colon:\n```gg\nfn mix(x: u64) -> u64 overflow: wrap:\n    return x * 1000000007 + 123456789\n```",
    "wrapping": "**wrapping** (Scoped Wrapping Arithmetic)\n\nInside a `wrapping:` block, integer `+`, `-`, and `*` wrap instead of trapping. Code after the block returns to the surrounding overflow mode.\n```gg\nres: i32 = 0\nwrapping:\n    res = a + 1\n```",
    "wrap": "**wrap** (Overflow Mode)\n\nUsed as `overflow: wrap`. Integer `+`, `-`, and `*` use two's-complement wrapping and do not trap.",
    "trap": "**trap** (Overflow Mode)\n\nUsed as `overflow: trap`. Integer `+`, `-`, and `*` trap on overflow (debug and release), which is also the default when no `overflow:` directive is present.",
    "impl": "**impl** (Method Block)\n\nGroups methods of a type; `Self` names the type.\n```gg\nimpl Point:\n    fn len2(self) -> i32:\n        return self.x * self.x\n```",
    "type": "**type** (Type Alias)\n\n```gg\ntype Id = u32\n```",
    "unsafe": "**unsafe** (Unsafe Block)\n\nAllows raw pointer operations (`p[i]`, `addr`, `addr_mut`, `ptr_cast`, `ptr_offset`, `ptr_to_int`, `int_to_ptr`, `cstr_to_string`, `string_to_cstr`) and calling pointer-taking/returning or variadic extern functions.\n```gg\nunsafe:\n    p = addr_mut(x)\n```",
    "mut": "**mut** (Mutable Raw Pointer)\n\nSpecifies a mutable raw pointer type (`*mut T`). Must be accessed within an `unsafe:` block.",
    "null": "**null** (Null Pointer Literal)\n\nPointer literal whose type is inferred from context (e.g., `p: *mut u8 = null`).",
    "return": "**return** (Function Return)\n\nExits function early and optionally returns a value.",
    "break": "**break** (Break Loop)\n\nTerminates innermost enclosing loop.",
    "continue": "**continue** (Continue Loop)\n\nSkips to next iteration of loop.",
    "pass": "**pass** (Empty Statement)\n\nDoes nothing; used to syntactically fill empty blocks.",
    "and": "**and** (Logical AND)\n\nEvaluates to `true` if both sides are true.",
    "or": "**or** (Logical OR)\n\nEvaluates to `true` if at least one side is true.",
    "not": "**not** (Logical NOT)\n\nInverts logical boolean value.",
    "true": "**true** (Boolean True)",
    "false": "**false** (Boolean False)",
}

BUILTIN_DOCS = {
    "print": "**print**(args...)\n\nPrints given arguments to standard output followed by a newline. Structs, lists, arrays, and enums print their contents.\n```gg\nprint(\"Result:\", 42)\nprint(point, [1, 2, 3])\n```",
    "panic": "**panic**(message: str | string)\n\nTerminates program immediately with an error message.\n```gg\npanic(\"Unexpected condition\")\npanic(f\"bad index: {i}\")\n```",
    "input": "**input**() -> str\n\nReads a line from standard input and returns it as `str`.\n```gg\nname = input()\n```",
    "addr": "**addr**(x) -> *T\n\nReturns raw read-only pointer to `x` (requires `unsafe:`). Descriptive alias: `address_of`.",
    "address_of": "**address_of**(x) -> *T\n\nReturns raw read-only pointer to `x` (requires `unsafe:`).",
    "addr_mut": "**addr_mut**(x) -> *mut T\n\nReturns mutable raw pointer to `x` (requires `unsafe:`). Descriptive alias: `address_of_mut`.",
    "address_of_mut": "**address_of_mut**(x) -> *mut T\n\nReturns mutable raw pointer to `x` (requires `unsafe:`).",
    "ptr_cast": "**ptr_cast**[*Target](p) -> *Target\n\nCasts raw pointer `p` to pointer of target type (requires `unsafe:`). Descriptive alias: `pointer_cast`.",
    "pointer_cast": "**pointer_cast**[*Target](p) -> *Target\n\nCasts raw pointer `p` to pointer of target type (requires `unsafe:`).",
    "ptr_offset": "**ptr_offset**(p, offset) -> *T\n\nCalculates pointer offset by `offset` elements (requires `unsafe:`). Descriptive alias: `pointer_offset`.",
    "pointer_offset": "**pointer_offset**(p, offset) -> *T\n\nCalculates pointer offset by `offset` elements (requires `unsafe:`).",
    "ptr_to_int": "**ptr_to_int**(p) -> usize\n\nConverts raw pointer to `usize` address (requires `unsafe:`). Descriptive alias: `pointer_to_int`.",
    "pointer_to_int": "**pointer_to_int**(p) -> usize\n\nConverts raw pointer to `usize` address (requires `unsafe:`).",
    "int_to_ptr": "**int_to_ptr**[*T](address: usize) -> *T\n\nConverts integer address to raw pointer (requires `unsafe:`). Descriptive alias: `int_to_pointer`.",
    "int_to_pointer": "**int_to_pointer**[*T](address: usize) -> *T\n\nConverts integer address to raw pointer (requires `unsafe:`).",
    "cstr_to_string": "**cstr_to_string**(p: *u8) -> string\n\nConverts null-terminated C string to Greengold `string` (requires `unsafe:`).",
    "string_to_cstr": "**string_to_cstr**(s: string) -> *u8\n\nReturns pointer to underlying null-terminated C string bytes (requires `unsafe:`).",
    "string": "**string** (Heap String, Core)\n\nOwned, growable UTF-8 string. Constructors: `string.new()`, `string.from(\"..\")`. Methods: `.append(..)`, `.append_str(..)`, `.append_byte(..)`, `.as_str()`. Automatically freed at scope end.",
    "Optional": "**Optional[T]** (Prelude Enum)\n\nRepresents an optional value that may or may not be present.\n```gg\nenum Optional[T]:\n    Valid(T)\n    None\n```",
    "Result": "**Result[T, E]** (Prelude Enum)\n\nRepresents an operation that can result in success (`Ok`) or error (`Err`).\n```gg\nenum Result[T, E]:\n    Ok(T)\n    Err(E)\n```",
    "Valid": "**Valid**(value: T) -> Optional[T]\n\nConstructs an `Optional` containing a value.",
    "None": "**None** -> Optional[T]\n\nEmpty `Optional` variant.",
    "Ok": "**Ok**(value: T) -> Result[T, E]\n\nSuccessful `Result` variant.",
    "Err": "**Err**(error: E) -> Result[T, E]\n\nError `Result` variant.",
    "Box": "**Box[T]** (Heap Box)\n\nSingle value allocated on heap memory. Automatically freed (`drop`) at scope end.",
    "List": "**List[T]** (Dynamic Array)\n\nDynamically growing heap array. Has methods `.push()`, `.pop()`, `.len`.",
    "wrapping_add": "**wrapping_add**\n\nInteger addition that wraps on overflow (two's complement). Infix or call.\n```gg\ns = a wrapping_add b\ns2 = wrapping_add[i32](a, b)\n```",
    "wrapping_sub": "**wrapping_sub**\n\nInteger subtraction that wraps on overflow.\n```gg\nd = a wrapping_sub b\n```",
    "wrapping_mul": "**wrapping_mul**\n\nInteger multiplication that wraps on overflow.\n```gg\np = a wrapping_mul b\n```",
    "saturating_add": "**saturating_add**\n\nInteger addition that clamps to the type's min or max on overflow.\n```gg\ns = a saturating_add b\n```",
    "saturating_sub": "**saturating_sub**\n\nInteger subtraction that clamps to the type's min or max on overflow.\n```gg\nd = a saturating_sub b\n```",
    "saturating_mul": "**saturating_mul**\n\nInteger multiplication that clamps to the type's min or max on overflow.\n```gg\np = a saturating_mul b\n```",
    "checked_add": "**checked_add** -> Optional[T]\n\nInteger addition that returns `None` on overflow and `Valid(sum)` otherwise.\n```gg\ns = a checked_add b\n```",
    "checked_sub": "**checked_sub** -> Optional[T]\n\nInteger subtraction that returns `None` on overflow and `Valid(diff)` otherwise.\n```gg\nd = a checked_sub b\n```",
    "checked_mul": "**checked_mul** -> Optional[T]\n\nInteger multiplication that returns `None` on overflow and `Valid(prod)` otherwise.\n```gg\np = a checked_mul b\n```",
}

PRIMITIVE_DOCS = {
    "int": "**int**: Alias for `i32`, except in a bounded integer (`int in lo..hi`), where it means `i64`",
    "uint": "**uint**: Alias for `u32` (32-bit unsigned integer)",
    "float": "**float**: Alias for `f32` (32-bit floating point number)",
    "double": "**double**: Alias for `f64` (64-bit floating point number)",
    "i8": "**i8**: 8-bit signed integer (-128 .. 127)",
    "i16": "**i16**: 16-bit signed integer (-32,768 .. 32,767)",
    "i32": "**i32**: 32-bit signed integer (default integer type)",
    "i64": "**i64**: 64-bit signed integer",
    "isize": "**isize**: 64-bit signed integer on the supported hosts",
    "u8": "**u8**: 8-bit unsigned integer (byte / character code, 0 .. 255)",
    "u16": "**u16**: 16-bit unsigned integer (0 .. 65,535)",
    "u32": "**u32**: 32-bit unsigned integer (0 .. 4,294,967,295)",
    "u64": "**u64**: 64-bit unsigned integer",
    "usize": "**usize**: 64-bit unsigned integer on the supported hosts. Index and length type",
    "f32": "**f32**: 32-bit floating point number (single precision IEEE 754)",
    "f64": "**f64**: 64-bit floating point number (double precision IEEE 754, default float)",
    "bool": "**bool**: Boolean type (`true` or `false`)",
    "str": "**str**: Read-only view of bytes. A function that returns nothing omits `-> T`.",
}


# --- Helper Functions ---------------------------------------------------

def uri_to_path(uri: str) -> Path:
    """Converts LSP URI string to local Path object."""
    parsed = urllib.parse.urlparse(uri)
    path_str = urllib.parse.unquote(parsed.path)
    if os.name == "nt" and parsed.netloc:
        path_str = f"//{parsed.netloc}{path_str}"
    elif re.match(r"/[A-Za-z]:", path_str):
        path_str = path_str[1:]  # file:///c:/dir -> c:/dir, the same on every OS
    return Path(path_str)


def _import_completions(cur_file: Path, line: int, end_col: int,
                        str_prefix: Optional[str], name_prefix: str) -> list[dict[str, Any]]:
    """Completion items for `import ...`: only the directory named by what is already typed is read."""
    from .cli import DEP_ROOTS, STD_DIR

    quoted = str_prefix is not None
    sep = "/" if quoted else "."
    head, _, partial = (str_prefix if quoted else name_prefix).rpartition(sep)
    segs = head.split(sep) if head else []
    here = cur_file.parent

    # (directory to list, label for it when it is a virtual top-level folder)
    dirs: list[tuple[Path, str]] = []
    if not segs:
        dirs.append((here, "local file"))
    else:
        first, rest = segs[0], segs[1:]
        if first == "std":
            dirs.append((STD_DIR.joinpath(*rest), "standard library"))
        elif first in DEP_ROOTS:
            dirs.append((Path(DEP_ROOTS[first]).joinpath(*rest), f"dependency {first}"))
        dirs.append((here.joinpath(*segs), "local file"))

    entries: list[tuple[str, bool, str]] = []  # (name, is_folder, origin)
    if not segs:
        entries += [("std", True, "standard library")] + [(d, True, f"dependency {d}") for d in DEP_ROOTS]
    for d, origin in dirs:
        try:
            with os.scandir(d) as it:
                for e in it:
                    if e.name.startswith((".", "_")):
                        continue
                    if e.is_dir():
                        entries.append((e.name, True, origin))
                    elif e.name.endswith(".gg"):
                        if Path(e.path).resolve() == cur_file.resolve():
                            continue
                        entries.append((e.name if quoted else e.name[:-3], False, origin))
        except OSError:
            continue

    items: list[dict[str, Any]] = []
    seen: set[tuple[str, bool]] = set()
    for name, is_folder, origin in sorted(entries, key=lambda t: (not t[1], t[0])):
        if (name, is_folder) in seen or not name.lower().startswith(partial.lower()):
            continue
        if not quoted and not name.isidentifier():
            continue
        seen.add((name, is_folder))
        text = name + sep if is_folder else name
        item: dict[str, Any] = {
            "label": name,
            "kind": CompletionItemKind.Folder if is_folder else CompletionItemKind.Module,
            "detail": origin,
            "filterText": name,
            "textEdit": {"range": {"start": {"line": line, "character": end_col - len(partial)},
                                   "end": {"line": line, "character": end_col}},
                         "newText": text},
        }
        if is_folder:  # keep going: show the folder's contents right away
            item["command"] = {"title": "Suggest", "command": "editor.action.triggerSuggest"}
        items.append(item)
    return items


def path_to_uri(path: Path | str) -> str:
    """Converts Path object to standard file:// URI."""
    p = Path(path).resolve()
    return p.as_uri()


def same_file(path_a: Path | str | None, path_b: Path | str | None) -> bool:
    """Checks if two file paths point to the same physical file."""
    if not path_a or not path_b:
        return False
    try:
        return Path(path_a).resolve() == Path(path_b).resolve()
    except Exception:
        return str(path_a) == str(path_b)


_PATH_KEYS: dict[str, str] = {}


def _path_key(path: Path | str | None) -> str:
    """Resolved path, cached. `Path.resolve()` is a syscall per call on Windows."""
    if not path:
        return ""
    text = str(path)
    cached = _PATH_KEYS.get(text)
    if cached is not None:
        return cached
    try:
        key = os.path.normcase(str(Path(text).resolve()))
    except Exception:
        key = os.path.normcase(text)
    _PATH_KEYS[text] = key
    return key


def format_type(t: Optional[TypeRef]) -> str:
    if t is None:
        return "void"
    if getattr(t, "is_slice", False) and getattr(t, "elem", None):
        return f"[]{format_type(t.elem)}"
    if getattr(t, "is_array", False) and getattr(t, "elem", None):
        return f"[?]{format_type(t.elem)}"
    if getattr(t, "args", None):
        base_name = getattr(t, "base", None) or t.name
        return f"{base_name}[{', '.join(format_type(a) for a in t.args)}]"
    return getattr(t, "name", "void") or "void"


# --- Greengold Code Formatter --------------------------------------------

def format_greengold_source(source: str) -> str:
    """The same canonical form as `gg fmt`."""
    from .fmt import format_source
    return format_source(source)


# --- Scope and Local Symbol Resolvers ---------------------------------------

@dataclass
class LocalSymbol:
    name: str
    kind: str  # "param", "var", "loop", "match"
    display: str
    line: int
    col: int
    mutable: bool = False
    node: Any = None


def _find_enclosing_func(decls: list[Node], line_1: int, total_lines: int) -> Optional[FuncDecl]:
    """Finds FuncDecl enclosing the cursor line. Prevents conflicts with other functions."""
    candidates: list[Node] = []
    for decl in decls:
        if getattr(decl, "is_lambda", False):
            continue  # lifted lambdas sit inside the function that contains them
        if hasattr(decl, "line") and getattr(decl, "line", 0) > 0:
            candidates.append(decl)
    candidates.sort(key=lambda d: getattr(d, "line", 0))

    for i, decl in enumerate(candidates):
        if not isinstance(decl, FuncDecl):
            continue
        start_line = decl.line
        end_line = total_lines
        if i + 1 < len(candidates):
            end_line = getattr(candidates[i + 1], "line", total_lines) - 1
        if start_line <= line_1 <= end_line:
            return decl
    return None


_MODE_REASON = {
    "read": "the body only reads it",
    "lend": "the body changes it, so the argument must be `var`",
    "consume": "the body keeps it, so the argument is moved",
}


def _inferred_note(p: Any) -> str:
    """Markdown note for a parameter whose mode the compiler inferred."""
    if not getattr(p, "mode_inferred", False) or not p.mode:
        return ""
    return f"\n\n*inferred `{p.mode}`*: {_MODE_REASON.get(p.mode, '')}"


_MODE_ORDER = ("read", "lend", "consume")

_FIXED_TIP = ("*inferred `fixed`*: nothing changes this variable, so it is treated as `fixed`. "
              "Changing it later removes this hint.")


def _pretty_fn(ty: str) -> str:
    """`fn(i32,i32)->void` -> `fn(i32, i32)`. Keeps a non-void result."""
    depth = 0
    arrow = -1
    for i, ch in enumerate(ty):
        if ch in "([":
            depth += 1
        elif ch in ")]":
            depth = max(0, depth - 1)
        elif ch == "-" and depth == 0 and ty.startswith("->", i):
            arrow = i
            break
    head, ret = (ty, "") if arrow < 0 else (ty[:arrow], ty[arrow + 2:])
    pretty: list[str] = []
    depth = 0
    for i, ch in enumerate(head):
        if ch in "([":
            depth += 1
        elif ch in ")]":
            depth = max(0, depth - 1)
        if ch == "," and not (i + 1 < len(head) and head[i + 1] == " "):
            pretty.append(", ")
            continue
        pretty.append(ch)
    shown = "".join(pretty)
    if ret in ("", "void"):
        return shown
    return f"{shown} -> {ret}"


def _shown_ty(ty: str) -> str:
    """Source spelling of a canonical type: `shapes::Rectangle` is written `shapes.Rectangle`."""
    return ty.replace("::", ".")


def _display_ty(checker: Any, ty: str | None) -> str | None:
    """Type text for an inlay hint. Closure structs become their function signature."""
    if not isinstance(ty, str) or not ty or ty == ERR:
        return None
    if checker is not None and ty in getattr(checker, "closures", {}):
        return _shown_ty(_pretty_fn(checker._closure_signature(ty)))
    if ty.startswith("__"):
        return None
    if ty.startswith("fn(") or ty.startswith("Fn("):
        return _shown_ty(_pretty_fn(ty))
    return _shown_ty(ty)


def _ident_end(lines: list[str], line_1: int, col_1: int, name: str) -> int | None:
    """0-based index just after `name` on this line, searching from `col_1` (1-based)."""
    if not name or name.startswith("__") or line_1 < 1 or line_1 > len(lines):
        return None
    text = lines[line_1 - 1]
    i = max(0, col_1 - 1)
    while True:
        j = text.find(name, i)
        if j < 0:
            return None
        end = j + len(name)
        before_ok = j == 0 or not (text[j - 1].isalnum() or text[j - 1] == "_")
        after_ok = end >= len(text) or not (text[end].isalnum() or text[end] == "_")
        if before_ok and after_ok:
            return end
        i = j + 1


def _same_span_file(path_a: str | None, path_b: str | None) -> bool:
    if not path_a and not path_b:
        return True
    return same_file(path_a, path_b)


def _related_params(program: Program | None, p: Param) -> list[Param]:
    """This parameter plus generic instances of it (same source span)."""
    found = [p]
    if program is None:
        return found
    for inst in getattr(program, "func_instances", []) or []:
        if not isinstance(inst, FuncDecl):
            continue
        for ip in inst.params:
            if (ip is not p and ip.name == p.name and ip.line == p.line and ip.col == p.col
                    and _same_span_file(getattr(ip, "filename", None), getattr(p, "filename", None))):
                found.append(ip)
    return found


def _param_mode(program: Program | None, p: Param) -> str | None:
    """Inferred `read`/`lend`/`consume` when the source left the mode out.

    Generic instances can disagree; the hint then shows every mode (`read|lend`).
    """
    if getattr(p, "mode_length", 0) or p.name.startswith("__"):
        return None
    found: list[str] = []
    for q in _related_params(program, p):
        mode = q.mode if getattr(q, "mode_inferred", False) else ""
        if mode in _MODE_ORDER and mode not in found:
            found.append(mode)
    ordered = [m for m in _MODE_ORDER if m in found]
    if not ordered:
        return None
    if len(ordered) == 1:
        return ordered[0]
    return "|".join(ordered)


def _mode_tooltip(mode: str) -> str:
    if "|" in mode:
        return f"*inferred* `{mode}`: the mode depends on the type this generic function is used with"
    reason = _MODE_REASON.get(mode, "")
    return f"*inferred `{mode}`*: {reason}" if reason else f"*inferred `{mode}`*"


def _type_on_line(lines: list[str], line_1: int, col_1: int, name: str) -> int | None:
    """0-based index where the type starts after `name:`, if that type is on this line.

    `self` with no colon returns None. `xs: List` returns the index of `List`.
    """
    end = _ident_end(lines, line_1, col_1, name)
    if end is None or line_1 < 1 or line_1 > len(lines):
        return None
    text = lines[line_1 - 1]
    i = end
    while i < len(text) and text[i] in " \t":
        i += 1
    if i >= len(text) or text[i] != ":":
        return None
    i += 1
    while i < len(text) and text[i] in " \t":
        i += 1
    if i >= len(text):
        return None
    return i


def _param_resolved_ty(program: Program | None, checker: Any, p: Param) -> str | None:
    found: list[str] = []
    for q in _related_params(program, p):
        shown = _display_ty(checker, getattr(q, "ty", None))
        if shown and shown not in found:
            found.append(shown)
    if len(found) == 1 and found[0] != "Self":
        return found[0]
    return None


def _iter_nodes(node: Node):
    """Yield `node` and every node under it. Skips the iterator desugar copy."""
    yield from (n for n, _fn in _walk_with_file(node, None))


def _walk_with_file(node: Node, inherited: str | None):
    """Yield `(node, filename)`. A node with no filename keeps its parent's file.

    `for` and `match` are anchored with `_header`, which does not record a filename.
    Prelude declarations do, so their children stay in the prelude file.
    """
    seen: set[int] = set()

    def walk(n: Node, file: str | None):
        if not isinstance(n, Node):
            return
        mark = id(n)
        if mark in seen:
            return
        seen.add(mark)
        file = getattr(n, "filename", None) or file
        yield n, file
        for key, value in n.__dict__.items():
            if key == "desugared":
                continue
            if isinstance(value, Node):
                yield from walk(value, file)
            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, Node):
                        yield from walk(item, file)

    yield from walk(node, inherited)


def _for_in_elem(s: ForIn) -> tuple[str | None, str]:
    """Element type and the borrow mode the loop variable actually has."""
    if s.elem_ty and s.elem_ty != ERR:
        mode = ""
        if s.by_ref:
            mode = "lend" if s.mutable else "read"
        return s.elem_ty, mode
    desugared = getattr(s, "desugared", None)
    if isinstance(desugared, Node):
        for n in _iter_nodes(desugared):
            if not isinstance(n, Match):
                continue
            for arm in n.arms:
                for i, b in enumerate(arm.bindings):
                    if b.name == s.var and i < len(arm.payload_tys):
                        ty = arm.payload_tys[i]
                        if ty and ty != ERR:
                            return ty, ""
    return None, ""


def _closure_of(checker: Any, decl: FuncDecl) -> str | None:
    if checker is None:
        return None
    for closure, key in getattr(checker, "closures", {}).items():
        info = checker.funcs.get(key)
        if info is None or not getattr(info.decl, "is_lambda", False):
            continue
        other = info.decl
        if other is decl or (other.line == decl.line and other.col == decl.col and other.name == decl.name):
            return closure
    return None


def _capture_label(checker: Any, closure: str) -> str | None:
    """Non-copy captures: `read`/`lend` borrows, or `consume` when the closure owns the value."""
    info = checker.structs.get(closure)
    if info is None or not info.fields:
        return None
    owning = closure in getattr(checker, "owning_closures", set())
    parts: list[str] = []
    for name, ty in info.fields.items():
        mode = info.field_modes.get(name)
        if mode in ("read", "lend"):
            parts.append(f"{mode} {name}")
        elif owning and checker._drop(ty):
            parts.append(f"consume {name}")
    if not parts:
        return None
    return "[" + ", ".join(parts) + "]"


def _inlay_hints(analysis: DocumentAnalysis, file_path: Path, rng: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Inlay hints for modes and types the source left out.

    A hint is only emitted when the text is not already written: an inferred parameter
    mode, a `=` binding (its type, and `fixed` when nothing changes it), a loop variable,
    a pattern binding, or a lambda capture. Omitted types follow the name as `: T`.
    """
    program = analysis.program
    checker = analysis.checker
    if program is None or checker is None:
        return []
    lines = analysis.source.splitlines()
    hints: list[dict[str, Any]] = []
    seen: set[tuple] = set()

    def add(line_1: int, character: int, label: str, tooltip: str, *, pad_left: bool = False, pad_right: bool = False) -> None:
        if line_1 < 1 or character < 0 or not label:
            return
        line_0 = line_1 - 1
        if line_0 >= len(lines):
            return
        key = (line_0, character, label)
        if key in seen:
            return
        seen.add(key)
        hint: dict[str, Any] = {
            "position": {"line": line_0, "character": character},
            "label": label,
            "kind": InlayHintKind.Type,
            "tooltip": {"kind": "markdown", "value": tooltip},
        }
        if pad_left:
            hint["paddingLeft"] = True
        if pad_right:
            hint["paddingRight"] = True
        hints.append(hint)

    def type_hint(line_1: int, col_1: int, name: str, ty: str | None, mode: str, tooltip: str | None = None) -> None:
        shown = _display_ty(checker, ty)
        if shown is None:
            return
        end = _ident_end(lines, line_1, col_1, name)
        if end is None:
            return
        body = f"{mode} {shown}" if mode in _MODE_ORDER else shown
        tip = tooltip or f"inferred `{body}`"
        add(line_1, end, f": {body}", tip)

    # Prelude and other files stay out of the walk. Resolving every node path
    # blocks the single-threaded server, so hover never gets a turn.
    target = _path_key(file_path)
    for decl in program.decls:
        decl_file = getattr(decl, "filename", None)
        if getattr(decl, "from_prelude", False) or _path_key(decl_file) != target:
            continue
        for node, filename in _walk_with_file(decl, decl_file):
            if getattr(node, "from_prelude", False) or _path_key(filename) != target:
                continue
            if isinstance(node, Param):
                mode = _param_mode(program, node)
                resolved = _param_resolved_ty(program, checker, node)
                # Where the written type starts. None for bare `self` (no colon on the line).
                # `Self` is rewritten to the owner type and loses its column, so the source decides.
                type_at = _type_on_line(lines, node.line, node.col, node.name)
                if type_at is None and node.name == "self":
                    end = _ident_end(lines, node.line, node.col, node.name)
                    if end is None:
                        continue
                    if mode and resolved:
                        add(node.line, end, f": {mode} {resolved}", _mode_tooltip(mode))
                    elif mode:
                        add(node.line, end, f": {mode} Self", _mode_tooltip(mode))
                    elif resolved:
                        add(node.line, end, f": {resolved}", f"inferred `{resolved}`")
                    continue
                if mode and type_at is not None:
                    add(node.line, type_at, mode, _mode_tooltip(mode), pad_right=True)
                    continue
                tref = node.type_ref
                if mode and tref is not None and tref.line > 0 and tref.col > 0:
                    add(tref.line, tref.col - 1, mode, _mode_tooltip(mode), pad_right=True)
            elif isinstance(node, VarDecl):
                if getattr(node, "auto_fixed", False) and not node.name.startswith("__"):
                    add(node.line, node.col - 1, "fixed", _FIXED_TIP, pad_right=True)
                if node.type_ref is not None or node.name.startswith("__"):
                    continue
                mode = ""
                if node.ref_mode in ("read", "lend") and not isinstance(node.value, BorrowExpr):
                    mode = node.ref_mode
                summary = _closure_summary(checker, node.ty or "")
                type_hint(node.line, node.col, node.name, node.ty, mode, summary)
            elif isinstance(node, ConstDecl):
                if node.type_ref is not None or node.name.startswith("__"):
                    continue
                type_hint(node.line, node.col, node.name, node.ty, "")
            elif isinstance(node, For):
                if node.var_ty and node.var_ty != ERR:
                    type_hint(node.line, node.col, node.var, node.var_ty, "")
            elif isinstance(node, ForIn):
                search = node.col
                if node.index_var:
                    type_hint(node.line, node.col, node.index_var, "usize", "")
                    end = _ident_end(lines, node.line, node.col, node.index_var)
                    if end is not None:
                        search = end + 1
                elem, mode = _for_in_elem(node)
                if elem:
                    end = _ident_end(lines, node.line, search, node.var)
                    if end is not None:
                        shown = _display_ty(checker, elem)
                        if shown:
                            body = f"{mode} {shown}" if mode else shown
                            how = f"borrowed `{mode}`" if mode else "inferred"
                            add(node.line, end, f": {body}", f"*(loop variable)* {how} `{shown}`")
            elif isinstance(node, Match):
                for arm in node.arms:
                    for i, b in enumerate(arm.bindings):
                        if b.name == "_" or b.name.startswith("__") or i >= len(arm.payload_tys):
                            continue
                        ty = arm.payload_tys[i]
                        mode = node.mode if node.mode in ("lend", "consume") else ""
                        end = _ident_end(lines, b.line, b.col, b.name)
                        shown = _display_ty(checker, ty)
                        if end is None or shown is None:
                            continue
                        body = f"{mode} {shown}" if mode else shown
                        how = f"`{mode}`" if mode else "inferred"
                        add(b.line, end, f": {body}", f"*(pattern variable)* {how} `{shown}`")
            elif isinstance(node, FuncDecl) and getattr(node, "is_lambda", False):
                closure = _closure_of(checker, node)
                if closure is None:
                    continue
                label = _capture_label(checker, closure)
                if not label:
                    continue
                summary = _closure_summary(checker, closure) or f"captures {label}"
                add(node.line, node.col - 1 + len("fn"), label, summary, pad_left=True, pad_right=True)

    hints.sort(key=lambda h: (h["position"]["line"], h["position"]["character"], h["label"]))
    return _hints_in_range(hints, rng)


def _hints_in_range(hints: list[dict[str, Any]], rng: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not rng:
        return hints
    start = rng.get("start") or {}
    end = rng.get("end") or {}
    lo = (start.get("line", 0), start.get("character", 0))
    hi = (end.get("line", 0), end.get("character", 0))
    return [h for h in hints if lo <= (h["position"]["line"], h["position"]["character"]) < hi]


def _closure_summary(checker: Any, closure: str) -> str | None:
    """Markdown for a closure type: its signature and how each captured variable is held."""
    if checker is None or closure not in getattr(checker, "closures", {}):
        return None
    sig = _shown_ty(checker._closure_signature(closure).replace("->void", ""))
    info = checker.structs[closure]
    owning = closure in getattr(checker, "owning_closures", set())
    lines = [f"*(closure)* `{sig}`" + (" â€” owns its captures" if owning else ""), ""]
    for name, ty in info.fields.items():
        mode = info.field_modes.get(name)
        if mode == "read":
            how = "borrowed `read`: cannot be changed or moved while the closure is used"
        elif mode == "lend":
            how = "borrowed `lend`: nothing else may use it while the closure is used"
        elif checker._drop(ty):
            how = "moved into the closure"
        else:
            how = "copied"
        lines.append(f"- `{name}: {_shown_ty(ty)}`: {how}")
    if not info.fields:
        lines.append("- captures nothing")
    return "\n".join(lines)


def _lambda_hover(prog: Any, checker: Any, line_1: int, col_1: int) -> str | None:
    """Hover on the `fn` of a lambda: the closure it became, or a plain function pointer."""
    for d in prog.decls:
        if isinstance(d, FuncDecl) and getattr(d, "is_lambda", False) and d.line == line_1 and d.col == col_1:
            summary = None
            if checker is not None:
                for closure, lam in getattr(checker, "closures", {}).items():
                    if lam.split("::")[-1] == d.name:
                        summary = _closure_summary(checker, closure)
            return summary or "*(lambda)* captures nothing: a plain function pointer `fn(...)`"
    return None


def _collect_local_symbols(decl: FuncDecl, target_line: int) -> list[LocalSymbol]:
    """Recursively collects visible local symbols (param, var, for, match) in function."""
    symbols: list[LocalSymbol] = []

    # 1. Parametreler
    for p in decl.params:
        mode_str = ("exclusive " if getattr(p, "exclusive", False) else "") + (f"{p.mode} " if p.mode else "")
        symbols.append(LocalSymbol(
            name=p.name,
            kind="param",
            display=f"*(parameter)* `{p.name}: {mode_str}{format_type(p.type_ref)}`{_inferred_note(p)}",
            line=p.line,
            col=p.col,
            node=p,
        ))

    # 2. Recursively collect local declarations inside body
    def walk_stmts(stmts: list[Stmt]) -> None:
        for stmt in stmts:
            if not isinstance(stmt, Node):
                continue
            if getattr(stmt, "line", 0) > target_line:
                continue

            if isinstance(stmt, VarDecl):
                raw_ty = stmt.ty or (format_type(stmt.type_ref) if stmt.type_ref else "unknown")
                ty_str = _shown_ty(raw_ty) if isinstance(raw_ty, str) else raw_ty
                prefix = "fixed " if not stmt.mutable or getattr(stmt, "auto_fixed", False) else ""
                symbols.append(LocalSymbol(
                    name=stmt.name,
                    kind="var",
                    display=f"*(variable)* `{prefix}{stmt.name}: {ty_str}`",
                    line=stmt.line,
                    col=stmt.col,
                    mutable=stmt.mutable,
                    node=stmt,
                ))
            elif isinstance(stmt, (For, ForIn)):
                symbols.append(LocalSymbol(
                    name=stmt.var,
                    kind="loop",
                    display=f"*(loop variable)* `{stmt.var}`",
                    line=stmt.line,
                    col=stmt.col,
                    node=stmt,
                ))
                if isinstance(stmt, ForIn) and stmt.index_var:
                    symbols.append(LocalSymbol(
                        name=stmt.index_var,
                        kind="loop",
                        display=f"*(loop index)* `{stmt.index_var}: usize`",
                        line=stmt.line,
                        col=stmt.col,
                        node=stmt,
                    ))
                walk_stmts(stmt.body)
            elif isinstance(stmt, If):
                for branch in stmt.branches:
                    walk_stmts(branch.body)
                if stmt.else_body:
                    walk_stmts(stmt.else_body)
            elif isinstance(stmt, While):
                walk_stmts(stmt.body)
            elif isinstance(stmt, Match):
                for arm in stmt.arms:
                    for b in getattr(arm, "bindings", []):
                        symbols.append(LocalSymbol(
                            name=b.name,
                            kind="match",
                            display=f"*(pattern variable)* `{b.name}`",
                            line=b.line,
                            col=b.col,
                            node=b,
                        ))
                    walk_stmts(arm.body)
            elif isinstance(stmt, Defer):
                if hasattr(stmt, "stmt") and isinstance(stmt.stmt, Stmt):
                    walk_stmts([stmt.stmt])
            elif isinstance(stmt, Wrapping):
                walk_stmts(stmt.body)

    walk_stmts(decl.body)
    return symbols


# --- LSP Analysis Result Record ------------------------------------------------

@dataclass
class DocumentAnalysis:
    source: str
    tokens: list[Token]
    program: Optional[Program]
    diags: DiagnosticBag
    checker: Optional[Any]
    imported_sources: dict[str, str]
    # Full inlay-hint list for this analysis. Range requests only filter it.
    inlay_hints: list | None = None


# --- Greengold Language Server ----------------------------------------------

class LanguageServer:
    def __init__(self, in_stream=None, out_stream=None) -> None:
        self.in_stream = in_stream or sys.stdin.buffer
        self.out_stream = out_stream or sys.stdout.buffer
        self.documents: dict[str, str] = {}
        self.analysis: dict[str, DocumentAnalysis] = {}
        self.running: bool = True
        self.root_path: Optional[Path] = None

    # --- Input / Output Communication --------------------------------------------

    def send_response(self, req_id: Any, result: Any = None, error: Any = None) -> None:
        payload: dict[str, Any] = {"jsonrpc": "2.0", "id": req_id}
        if error is not None:
            payload["error"] = error
        else:
            payload["result"] = result
        self._write_msg(payload)

    def send_notification(self, method: str, params: Any) -> None:
        payload = {"jsonrpc": "2.0", "method": method, "params": params}
        self._write_msg(payload)

    def _write_msg(self, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        header = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
        try:
            self.out_stream.write(header + body)
            self.out_stream.flush()
        except OSError:
            pass

    def run(self) -> int:
        """Main loop that reads and processes incoming JSON-RPC messages."""
        while self.running:
            try:
                headers: dict[str, str] = {}
                while True:
                    line = self.in_stream.readline()
                    if not line:
                        return 0
                    line_str = line.decode("latin1").strip("\r\n")
                    if not line_str:
                        if headers:
                            break
                        continue
                    if ":" in line_str:
                        k, v = line_str.split(":", 1)
                        headers[k.strip().lower()] = v.strip()

                if "content-length" not in headers:
                    continue

                content_len = int(headers["content-length"])
                body_bytes = b""
                while len(body_bytes) < content_len:
                    chunk = self.in_stream.read(content_len - len(body_bytes))
                    if not chunk:
                        return 0
                    body_bytes += chunk

                msg = json.loads(body_bytes.decode("utf-8"))
                self.handle_message(msg)
            except Exception as exc:
                logging.error("LSP loop error: %s\n%s", exc, traceback.format_exc())
        return 0

    def handle_message(self, msg: dict[str, Any]) -> None:
        method = msg.get("method")
        req_id = msg.get("id")
        params = msg.get("params")
        if params is None:
            params = {}

        if not method:
            # Ignore response message (no method, id present)
            return

        handler_name = "m_" + method.replace("/", "_").replace("$", "_")
        handler = getattr(self, handler_name, None)

        if handler is not None:
            try:
                result = handler(params)
                if req_id is not None:
                    self.send_response(req_id, result=result)
            except Exception as exc:
                logging.error("Handler error %s: %s\n%s", method, exc, traceback.format_exc())
                if req_id is not None:
                    self.send_response(req_id, error={"code": -32603, "message": str(exc)})
        else:
            if req_id is not None:
                self.send_response(req_id, error={"code": -32601, "message": f"Method not supported: {method}"})

    # --- Lifecycle Methods --------------------------------------------

    def m_initialize(self, params: dict[str, Any]) -> dict[str, Any]:
        workspace_folders = params.get("workspaceFolders")
        if workspace_folders and isinstance(workspace_folders, list) and len(workspace_folders) > 0:
            first_folder = workspace_folders[0]
            if isinstance(first_folder, dict) and "uri" in first_folder:
                self.root_path = uri_to_path(first_folder["uri"])

        if self.root_path is None:
            root_uri = params.get("rootUri")
            if root_uri:
                self.root_path = uri_to_path(root_uri)
            elif params.get("rootPath"):
                self.root_path = Path(params["rootPath"])

        return {
            "capabilities": {
                "textDocumentSync": {
                    "openClose": True,
                    "change": 1,  # Full sync
                    "save": {"includeText": True},
                },
                "hoverProvider": True,
                "inlayHintProvider": {"resolveProvider": False},
                "definitionProvider": True,
                "documentSymbolProvider": True,
                "completionProvider": {
                    "resolveProvider": False,
                    "triggerCharacters": [".", " ", '"'],
                },
                "documentFormattingProvider": True,
                "signatureHelpProvider": {
                    "triggerCharacters": ["(", ","],
                },
                "referencesProvider": True,
                "renameProvider": {
                    "prepareProvider": True,
                },
                "workspaceSymbolProvider": True,
                "codeActionProvider": {
                    "codeActionKinds": ["quickfix", "source.fixAll", "source.fixAll.greengold"],
                },
            },
            "serverInfo": {
                "name": "greengold-lsp",
                "version": "0.12.0",
            },
        }

    def m_initialized(self, params: dict[str, Any]) -> None:
        pass

    def m_shutdown(self, params: dict[str, Any]) -> None:
        self._shutdown_received = True
        return None

    def m_exit(self, params: dict[str, Any]) -> None:
        self.running = False

    # --- Document Events and Analysis --------------------------------------------

    def m_textDocument_didOpen(self, params: dict[str, Any]) -> None:
        doc = params.get("textDocument", {})
        uri = doc.get("uri")
        text = doc.get("text", "")
        if uri:
            self.documents[uri] = text
            self.analyze_and_publish(uri)

    def m_textDocument_didChange(self, params: dict[str, Any]) -> None:
        doc = params.get("textDocument", {})
        uri = doc.get("uri")
        changes = params.get("contentChanges", [])
        if uri and changes:
            # Full sync modunda son eleman tam metindir
            self.documents[uri] = changes[-1].get("text", "")
            self.analyze_and_publish(uri)

    def m_textDocument_didSave(self, params: dict[str, Any]) -> None:
        doc = params.get("textDocument", {})
        uri = doc.get("uri")
        if uri:
            text = doc.get("text")
            if text is not None:
                self.documents[uri] = text
            self.analyze_and_publish(uri)

    def m_textDocument_didClose(self, params: dict[str, Any]) -> None:
        doc = params.get("textDocument", {})
        uri = doc.get("uri")
        if uri:
            self.documents.pop(uri, None)
            self.analysis.pop(uri, None)

    def analyze_and_publish(self, uri: str) -> None:
        """Runs document through compiler pipeline and reports diagnostics to editor."""
        source = self.documents.get(uri, "")
        file_path = uri_to_path(uri)
        path_str = str(file_path)

        diags = DiagnosticBag()
        tokens = tokenize(source, diags)

        program: Optional[Program] = None
        imported_sources: dict[str, str] = {path_str: source}
        checker = None

        # Preserve previous valid AST (for completion/hover when syntax is temporarily broken while typing)
        prev_analysis = self.analysis.get(uri)
        if prev_analysis and prev_analysis.program:
            program = prev_analysis.program

        try:
            # Same pipeline as `gg check`: imports, inferred modes, closures, move and borrow checks.
            # A syntax error skips its line and the rest of the file is still checked.
            parsed_prog, imported_sources, diags, new_checker = analyze(
                [], initial_source=source, initial_filename=path_str, require_main=False)
            syntax_ok = not any(d.category == "syntax" for d in diags.items)
            has_decls = parsed_prog is not None and any(
                not getattr(d, "from_prelude", False) and _path_key(getattr(d, "filename", None)) == _path_key(file_path)
                for d in parsed_prog.decls
            )
            if (syntax_ok or has_decls or program is None) and parsed_prog is not None:
                program = parsed_prog
                checker = new_checker
            elif prev_analysis is not None:
                checker = prev_analysis.checker
        except Exception as exc:
            diags = DiagnosticBag()
            diags.error(f"Compiler internal error: {exc}", line=1, col=1)

        self.analysis[uri] = DocumentAnalysis(
            source=source,
            tokens=tokens,
            program=program,
            diags=diags,
            checker=checker,
            imported_sources=imported_sources,
        )

        lines = source.splitlines()
        max_line = max(0, len(lines) - 1) if lines else 0

        from .diagnostics import prepare
        prepare(diags.items)

        # Convert diagnostics to LSP format and publish
        lsp_diagnostics = []
        for d in diags.items:
            if d.hidden:
                continue
            target_file = d.filename or path_str
            is_this_file = same_file(target_file, file_path)

            line = max(0, d.line - 1)
            col = max(0, d.col - 1)
            length = max(1, getattr(d, "length", 1))

            msg = f"{d.code}: {d.message}" if d.code else d.message
            if getattr(d, "hint", None):
                msg += f"\n\n Hint: {d.hint}"

            if is_this_file:
                actual_line = min(line, max_line)
                actual_col = min(col, len(lines[actual_line])) if lines else 0

                related_info = []
                for note in getattr(d, "notes", []):
                    n_line = min(max(0, note.line - 1), max_line)
                    n_col = min(max(0, note.col - 1), len(lines[n_line])) if lines else 0
                    n_len = max(1, note.length)
                    related_info.append({
                        "location": {
                            "uri": uri,
                            "range": {
                                "start": {"line": n_line, "character": n_col},
                                "end": {"line": n_line, "character": n_col + n_len},
                            },
                        },
                        "message": note.text,
                    })

                lsp_diagnostics.append({
                    "range": {
                        "start": {"line": actual_line, "character": actual_col},
                        "end": {"line": actual_line, "character": actual_col + length},
                    },
                    "severity": DiagnosticSeverity.Error,
                    "source": "greengold",
                    "code": d.code,
                    "message": msg,
                    "relatedInformation": related_info,
                    "data": {"id": d.id},
                })
            else:
                # If there is an error in an imported file, add warning to import line in this file
                imp_line = 0
                imp_name = Path(target_file).name
                for idx, l_txt in enumerate(lines):
                    if imp_name in l_txt and "import" in l_txt:
                        imp_line = idx
                        break

                lsp_diagnostics.append({
                    "range": {
                        "start": {"line": imp_line, "character": 0},
                        "end": {"line": imp_line, "character": len(lines[imp_line]) if lines else 1},
                    },
                    "severity": DiagnosticSeverity.Error,
                    "source": "greengold",
                    "message": f"Error in imported file ({imp_name}): {msg}",
                })

        self.send_notification("textDocument/publishDiagnostics", {
            "uri": uri,
            "diagnostics": lsp_diagnostics,
        })

    # --- Code actions ------------------------------------------------------------

    @staticmethod
    def _text_edit(e: Any) -> dict[str, Any]:
        return {
            "range": {
                "start": {"line": e.start_line - 1, "character": e.start_col - 1},
                "end": {"line": e.end_line - 1, "character": e.end_col - 1},
            },
            "newText": e.replacement,
        }

    def m_textDocument_codeAction(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        """Quick fixes from the compiler's `fixes`, plus one action that applies every verified safe fix."""
        uri = params.get("textDocument", {}).get("uri", "")
        analysis = self.analysis.get(uri)
        if analysis is None:
            return []
        context = params.get("context", {}) or {}
        only = context.get("only") or []
        path_str = str(uri_to_path(uri))
        actions: list[dict[str, Any]] = []
        # Fix-all re-checks the file several times, so it runs only when asked for (on save, or from the menu).
        wants_fix_all = any(k.startswith("source") for k in only)
        wants_quick = not only or any(k.startswith("quickfix") for k in only)
        if wants_quick:
            rng = params.get("range", {})
            lo = rng.get("start", {}).get("line", 0) + 1
            hi = rng.get("end", {}).get("line", lo - 1) + 1
            by_id = {(d.get("data") or {}).get("id"): d for d in context.get("diagnostics", []) if isinstance(d, dict)}
            near = [d for d in analysis.diags.items
                    if not d.hidden and d.fixes and same_file(d.filename or path_str, path_str) and lo <= d.line <= hi]
            unchecked = [d for d in near if not getattr(d, "fixes_checked", False)]
            if unchecked:  # once per analysis: the cursor moving around asks again and again
                sources = dict(analysis.imported_sources)
                sources[path_str] = analysis.source
                try:
                    verify_fixes(analysis.diags.items, sources, path_str, limit=10, require_main=False,
                                 targets=unchecked)
                except Exception as exc:
                    logging.error("fix verification failed: %s", exc)
                for d in unchecked:
                    d.fixes_checked = True  # type: ignore[attr-defined]
            for d in near:
                for fix in d.fixes:
                    if not fix.edits or any(e.filename and not same_file(e.filename, path_str) for e in fix.edits):
                        continue
                    action: dict[str, Any] = {
                        "title": fix.description,
                        "kind": "quickfix",
                        "edit": {"changes": {uri: [self._text_edit(e) for e in fix.edits]}},
                        "isPreferred": bool(fix.verified and fix.applicability == "safe"),
                    }
                    lsp_diag = by_id.get(d.id)
                    if lsp_diag is not None:
                        action["diagnostics"] = [lsp_diag]
                    actions.append(action)
        if wants_fix_all and any(d.fixes for d in analysis.diags.items if not d.hidden):
            try:
                new_text, applied, _left = fix_source(analysis.source, path_str)
            except Exception as exc:
                logging.error("fix-all failed: %s", exc)
                new_text, applied = analysis.source, []
            if applied and new_text != analysis.source:
                line_count = analysis.source.count(chr(10))
                actions.append({
                    "title": f"Fix all safe problems ({len(applied)})",
                    "kind": "source.fixAll.greengold",
                    "edit": {"changes": {uri: [{
                        "range": {"start": {"line": 0, "character": 0},
                                  "end": {"line": line_count + 1, "character": 0}},
                        "newText": new_text,
                    }]}},
                })
        return actions

    # --- Helper: Find Token and Symbol at Position ---------------------------

    def _token_at(self, uri: str, line_1: int, col_1: int) -> Optional[Token]:
        analysis = self.analysis.get(uri)
        if not analysis:
            return None
        for t in analysis.tokens:
            if t.line == line_1 and (t.col <= col_1 <= t.col + t.length):
                return t
        return None

    def _word_at(self, source: str, line_0: int, char_0: int) -> tuple[str, int, int]:
        lines = source.splitlines()
        if not (0 <= line_0 < len(lines)):
            return "", char_0, char_0
        line_text = lines[line_0]
        if char_0 > len(line_text):
            char_0 = len(line_text)

        # Determine word boundaries [A-Za-z0-9_]
        start = char_0
        while start > 0 and (line_text[start - 1].isalnum() or line_text[start - 1] == "_"):
            start -= 1
        end = char_0
        while end < len(line_text) and (line_text[end].isalnum() or line_text[end] == "_"):
            end += 1

        return line_text[start:end], start, end

    # --- Hover Tooltips -------------------------------------------------

    def m_textDocument_hover(self, params: dict[str, Any]) -> Optional[dict[str, Any]]:
        uri = params.get("textDocument", {}).get("uri")
        pos = params.get("position", {})
        line_0 = pos.get("line", 0)
        char_0 = pos.get("character", 0)

        analysis = self.analysis.get(uri)
        if not analysis:
            return None

        word, start_c, end_c = self._word_at(analysis.source, line_0, char_0)
        if not word:
            return None

        line_1 = line_0 + 1

        # 0. A lambda: what it captures and how
        if word == "fn" and analysis.program is not None:
            lam = _lambda_hover(analysis.program, analysis.checker, line_1, start_c + 1)
            if lam is not None:
                return {"contents": {"kind": "markdown", "value": lam}}

        # 1. Keyword Documentation
        # `wrap` / `trap` are only overflow modes after `overflow:`.
        keyword_word = word
        if word in ("wrap", "trap"):
            line_text = analysis.source.splitlines()[line_0] if line_0 < len(analysis.source.splitlines()) else ""
            if not re.search(rf"\boverflow\s*:\s*{word}\b", line_text):
                keyword_word = ""
        if keyword_word in KEYWORD_DOCS:
            return {
                "contents": {"kind": "markdown", "value": KEYWORD_DOCS[keyword_word]},
                "range": {
                    "start": {"line": line_0, "character": start_c},
                    "end": {"line": line_0, "character": end_c},
                },
            }

        # 2. Built-in / Prelude Types and Functions
        if word in PRIMITIVE_DOCS:
            return {
                "contents": {"kind": "markdown", "value": PRIMITIVE_DOCS[word]},
                "range": {
                    "start": {"line": line_0, "character": start_c},
                    "end": {"line": line_0, "character": end_c},
                },
            }

        if word in BUILTIN_DOCS:
            return {
                "contents": {"kind": "markdown", "value": BUILTIN_DOCS[word]},
                "range": {
                    "start": {"line": line_0, "character": start_c},
                    "end": {"line": line_0, "character": end_c},
                },
            }

        # 3. Search User-Defined Symbols in AST
        if analysis.program:
            prog = analysis.program
            total_lines = len(analysis.source.splitlines())

            # 3a. If inside function, search symbols in local scope
            enclosing = _find_enclosing_func(prog.decls, line_1, total_lines)
            if enclosing:
                locals_in_scope = _collect_local_symbols(enclosing, line_1)
                matching = [s for s in locals_in_scope if s.name == word]
                if matching:
                    sym = matching[-1]
                    closure = _closure_summary(analysis.checker, getattr(sym.node, "ty", None) or "")
                    if sym.kind == "var" and closure is not None:
                        return {"contents": {"kind": "markdown", "value": f"*(variable)* `{word}`\n\n{closure}"}}
                    return {"contents": {"kind": "markdown", "value": sym.display}}

            # 3b. Top-level declarations (function, struct, enum, feature, const, extern)
            for decl in prog.decls:
                if isinstance(decl, FuncDecl) and decl.name == word:
                    tparams_str = f"[{', '.join(decl.type_params)}]" if decl.type_params else ""
                    params_str = ", ".join(
                        f"{p.name}: {'exclusive ' if getattr(p, 'exclusive', False) else ''}"
                        f"{p.mode + ' ' if p.mode else ''}{format_type(p.type_ref)}"
                        for p in decl.params
                    )
                    ret_str = f" -> {format_type(decl.ret)}" if decl.ret else ""
                    owner_str = f"{_shown_ty(decl.owner)}." if decl.owner else ""
                    ov = getattr(decl, "overflow_mode", None)
                    ov_str = f" overflow: {ov}" if ov else ""
                    code = f"fn {owner_str}{decl.name}{tparams_str}({params_str}){ret_str}{ov_str}"
                    notes = "".join(
                        f"\n- `{p.name}`: inferred `{p.mode}` ({_MODE_REASON.get(p.mode, '')})"
                        for p in decl.params if getattr(p, "mode_inferred", False) and p.mode)
                    extra = f"\n\nParameter modes left out in the source:{notes}" if notes else ""
                    return {"contents": {"kind": "markdown", "value": f"```gg\n{code}\n```{extra}"}}

                if isinstance(decl, StructDecl):
                    if decl.name == word:
                        tparams_str = f"[{', '.join(decl.type_params)}]" if decl.type_params else ""
                        fields_str = "\n".join(f"    {f.name}: {format_type(f.type_ref)}" for f in decl.fields)
                        code = f"struct {decl.name}{tparams_str}:\n{fields_str}"
                        return {"contents": {"kind": "markdown", "value": f"```gg\n{code}\n```"}}
                    for f in decl.fields:
                        if f.name == word:
                            md = f"*(alan)* `{decl.name}.{f.name}: {format_type(f.type_ref)}`"
                            return {"contents": {"kind": "markdown", "value": md}}

                if isinstance(decl, EnumDecl):
                    if decl.name == word:
                        tparams_str = f"[{', '.join(decl.type_params)}]" if decl.type_params else ""
                        variants_str = "\n".join(
                            f"    {v.name}{'(' + ', '.join(format_type(p) for p in v.payload) + ')' if v.payload else ''}"
                            for v in decl.variants
                        )
                        code = f"enum {decl.name}{tparams_str}:\n{variants_str}"
                        return {"contents": {"kind": "markdown", "value": f"```gg\n{code}\n```"}}
                    for v in decl.variants:
                        if v.name == word:
                            payload_str = f"({', '.join(format_type(p) for p in v.payload)})" if v.payload else ""
                            md = f"*(varyant)* `enum {decl.name}.{v.name}{payload_str}`"
                            return {"contents": {"kind": "markdown", "value": md}}

                if isinstance(decl, FeatureDecl):
                    if decl.name == word:
                        methods_str = "\n".join(
                            f"    fn {m.name}({', '.join(p.name for p in m.params)})" + (f" -> {format_type(m.ret)}" if m.ret else "")
                            for m in decl.methods
                        )
                        code = f"feature {decl.name}:\n{methods_str}"
                        return {"contents": {"kind": "markdown", "value": f"```gg\n{code}\n```"}}
                    for m in decl.methods:
                        if m.name == word:
                            params_str = ", ".join(f"{p.name}: {format_type(p.type_ref)}" for p in m.params)
                            ret_str = f" -> {format_type(m.ret)}" if m.ret else ""
                            md = f"*(feature method)* `feature {decl.name}.{m.name}({params_str}){ret_str}`"
                            return {"contents": {"kind": "markdown", "value": md}}

                if isinstance(decl, ConstDecl) and decl.name == word:
                    raw_ty = decl.ty or (format_type(decl.type_ref) if decl.type_ref else "")
                    ty_str = _shown_ty(raw_ty) if isinstance(raw_ty, str) else raw_ty
                    code = f"const {decl.name}: {ty_str}"
                    return {"contents": {"kind": "markdown", "value": f"```gg\n{code}\n```"}}

                if isinstance(decl, ExternFuncDecl) and decl.name == word:
                    hdr = f'"{decl.header}" ' if decl.header else ""
                    params_str = ", ".join(f"{p.name}: {format_type(p.type_ref)}" for p in decl.params)
                    ret_str = f" -> {format_type(decl.ret)}" if decl.ret else ""
                    code = f"extern {hdr}fn {decl.name}({params_str}){ret_str}"
                    return {"contents": {"kind": "markdown", "value": f"```gg\n{code}\n```"}}

        return None

    # --- Inlay Hints --------------------------------------------------------

    def m_textDocument_inlayHint(self, params: dict[str, Any] | None) -> list[dict[str, Any]]:
        params = params or {}
        uri = params.get("textDocument", {}).get("uri")
        analysis = self.analysis.get(uri)
        if not analysis:
            return []
        if analysis.inlay_hints is None:
            analysis.inlay_hints = _inlay_hints(analysis, uri_to_path(uri), None)
        return _hints_in_range(analysis.inlay_hints, params.get("range"))

    # --- Definition (Go to Definition / F12) ---------------------------------------

    def m_textDocument_definition(self, params: dict[str, Any]) -> Optional[dict[str, Any]]:
        uri = params.get("textDocument", {}).get("uri")
        pos = params.get("position", {})
        line_0 = pos.get("line", 0)
        char_0 = pos.get("character", 0)

        analysis = self.analysis.get(uri)
        if not analysis:
            return None

        cur_file = uri_to_path(uri)

        # If cursor is on an import string, jump to file
        line_text = analysis.source.splitlines()[line_0] if line_0 < len(analysis.source.splitlines()) else ""
        if "import " in line_text:
            m = re.search(r'import\s+(?:"([^"]+)"|([A-Za-z_][A-Za-z0-9_.]*))', line_text)
            if m:
                imp_path = m.group(1) or m.group(2)
                if imp_path and not imp_path.endswith(".gg") and "." in imp_path and "/" not in imp_path:
                    imp_path = imp_path.replace(".", "/") + ".gg"
                resolved = _resolve_import_target(cur_file.parent, imp_path)
                if resolved.exists():
                    return {
                        "uri": path_to_uri(resolved),
                        "range": {
                            "start": {"line": 0, "character": 0},
                            "end": {"line": 0, "character": 0},
                        },
                    }

        word, _, _ = self._word_at(analysis.source, line_0, char_0)
        if not word or word in KEYWORDS:
            return None

        line_1 = line_0 + 1

        if analysis.program:
            prog = analysis.program
            total_lines = len(analysis.source.splitlines())

            # 1. Local symbols of current function (param, variable, loop, match)
            enclosing = _find_enclosing_func(prog.decls, line_1, total_lines)
            if enclosing:
                locals_in_scope = _collect_local_symbols(enclosing, line_1)
                matching = [s for s in locals_in_scope if s.name == word]
                if matching:
                    sym = matching[-1]
                    s_line = max(0, sym.line - 1)
                    s_col = max(0, sym.col - 1)
                    return {
                        "uri": uri,
                        "range": {
                            "start": {"line": s_line, "character": s_col},
                            "end": {"line": s_line, "character": s_col + len(sym.name)},
                        },
                    }

            # 2. Top-level declarations. `math.sqrt` prefers the imported module.
            qual = None
            prefix = line_text[:char_0]
            qual_m = re.search(r"([A-Za-z_][A-Za-z0-9_]*)\.\s*$", prefix)
            if qual_m:
                qual = qual_m.group(1)
            cur_slug = ""
            for decl in prog.decls:
                if same_file(getattr(decl, "filename", "") or "", cur_file):
                    cur_slug = getattr(decl, "module_slug", "") or ""
                    break
            want_slug = None
            if qual:
                for local, target, names, _decl in (prog.imports or {}).get(cur_slug, []):
                    if not names and local == qual:
                        want_slug = target
                        break

            def _decl_ok(decl: Node) -> bool:
                if want_slug is None:
                    return True
                return (getattr(decl, "module_slug", "") or "") == want_slug

            ordered = list(prog.decls)
            if want_slug is None:
                ordered.sort(key=lambda d: 0 if same_file(getattr(d, "filename", "") or "", cur_file) else 1)
            for decl in ordered:
                if not _decl_ok(decl):
                    continue
                d_file = getattr(decl, "filename", None)
                if not d_file or d_file == "<source>" or same_file(d_file, cur_file):
                    target_uri = uri
                else:
                    target_uri = path_to_uri(d_file)

                if isinstance(decl, FuncDecl) and decl.name == word:
                    return {
                        "uri": target_uri,
                        "range": {
                            "start": {"line": max(0, decl.line - 1), "character": max(0, decl.col - 1)},
                            "end": {"line": max(0, decl.line - 1), "character": max(0, decl.col - 1) + len(decl.name)},
                        },
                    }
                if isinstance(decl, StructDecl):
                    if decl.name == word:
                        return {
                            "uri": target_uri,
                            "range": {
                                "start": {"line": max(0, decl.line - 1), "character": max(0, decl.col - 1)},
                                "end": {"line": max(0, decl.line - 1), "character": max(0, decl.col - 1) + len(decl.name)},
                            },
                        }
                    for f in decl.fields:
                        if f.name == word:
                            return {
                                "uri": target_uri,
                                "range": {
                                    "start": {"line": max(0, f.line - 1), "character": max(0, f.col - 1)},
                                    "end": {"line": max(0, f.line - 1), "character": max(0, f.col - 1) + len(f.name)},
                                },
                            }
                if isinstance(decl, EnumDecl):
                    if decl.name == word:
                        return {
                            "uri": target_uri,
                            "range": {
                                "start": {"line": max(0, decl.line - 1), "character": max(0, decl.col - 1)},
                                "end": {"line": max(0, decl.line - 1), "character": max(0, decl.col - 1) + len(decl.name)},
                            },
                        }
                    for v in decl.variants:
                        if v.name == word:
                            return {
                                "uri": target_uri,
                                "range": {
                                    "start": {"line": max(0, v.line - 1), "character": max(0, v.col - 1)},
                                    "end": {"line": max(0, v.line - 1), "character": max(0, v.col - 1) + len(v.name)},
                                },
                            }
                if isinstance(decl, FeatureDecl):
                    if decl.name == word:
                        return {
                            "uri": target_uri,
                            "range": {
                                "start": {"line": max(0, decl.line - 1), "character": max(0, decl.col - 1)},
                                "end": {"line": max(0, decl.line - 1), "character": max(0, decl.col - 1) + len(decl.name)},
                            },
                        }
                    for m in decl.methods:
                        if m.name == word:
                            return {
                                "uri": target_uri,
                                "range": {
                                    "start": {"line": max(0, m.line - 1), "character": max(0, m.col - 1)},
                                    "end": {"line": max(0, m.line - 1), "character": max(0, m.col - 1) + len(m.name)},
                                },
                            }
                if isinstance(decl, ConstDecl) and decl.name == word:
                    return {
                        "uri": target_uri,
                        "range": {
                            "start": {"line": max(0, decl.line - 1), "character": max(0, decl.col - 1)},
                            "end": {"line": max(0, decl.line - 1), "character": max(0, decl.col - 1) + len(decl.name)},
                        },
                    }
                if isinstance(decl, ExternFuncDecl) and decl.name == word:
                    return {
                        "uri": target_uri,
                        "range": {
                            "start": {"line": max(0, decl.line - 1), "character": max(0, decl.col - 1)},
                            "end": {"line": max(0, decl.line - 1), "character": max(0, decl.col - 1) + len(decl.name)},
                        },
                    }

        return None

    # --- Document Symbols (Anahat / Outline) ---------------------------------

    def m_textDocument_documentSymbol(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        uri = params.get("textDocument", {}).get("uri")
        analysis = self.analysis.get(uri)
        if not analysis or not analysis.program:
            return []

        cur_path = uri_to_path(uri)
        lines = analysis.source.splitlines()
        total_lines = len(lines)
        if total_lines == 0:
            return []

        file_decls: list[Node] = []
        for decl in analysis.program.decls:
            d_file = getattr(decl, "filename", None)
            if d_file and not same_file(d_file, cur_path):
                continue
            if hasattr(decl, "line") and 0 < decl.line <= total_lines:
                file_decls.append(decl)

        file_decls.sort(key=lambda d: getattr(d, "line", 0))

        def ensure_contains(outer: dict[str, Any], inner: dict[str, Any]) -> None:
            """Ensure outer['range'] geometrically encloses inner['range'] or inner['selectionRange']."""
            o_s = (outer["start"]["line"], outer["start"]["character"])
            i_s = (inner["start"]["line"], inner["start"]["character"])
            if o_s > i_s:
                outer["start"] = {"line": inner["start"]["line"], "character": inner["start"]["character"]}

            o_e = (outer["end"]["line"], outer["end"]["character"])
            i_e = (inner["end"]["line"], inner["end"]["character"])
            if o_e < i_e:
                outer["end"] = {"line": inner["end"]["line"], "character": inner["end"]["character"]}

        def build_symbol(
            name: str,
            detail: str,
            kind: int,
            start_line: int,
            start_col: int,
            end_line: int,
            children: Optional[list[dict[str, Any]]] = None,
        ) -> Optional[dict[str, Any]]:
            if not (0 <= start_line < total_lines):
                return None

            end_line = max(start_line, min(end_line, total_lines - 1))
            line_text = lines[start_line]

            # Find symbol name in line_text for precise selectionRange
            idx = line_text.find(name)
            if idx >= 0:
                sel_start = idx
                sel_end = idx + len(name)
            else:
                sel_start = min(start_col, len(line_text))
                sel_end = min(len(line_text), sel_start + len(name))
                if sel_end <= sel_start:
                    sel_end = sel_start + max(1, len(name))

            selection_range = {
                "start": {"line": start_line, "character": sel_start},
                "end": {"line": start_line, "character": sel_end},
            }

            end_char = len(lines[end_line]) if end_line < total_lines else 0
            sym_range = {
                "start": {"line": start_line, "character": 0},
                "end": {"line": end_line, "character": end_char},
            }

            # 1. Guarantee symbol range encloses its own selectionRange
            ensure_contains(sym_range, selection_range)

            # 2. Validate and enclose all children ranges
            valid_children = []
            if children:
                for c in children:
                    ensure_contains(c["range"], c["selectionRange"])
                    ensure_contains(sym_range, c["range"])
                    valid_children.append(c)

            sym_data: dict[str, Any] = {
                "name": name,
                "detail": detail,
                "kind": kind,
                "range": sym_range,
                "selectionRange": selection_range,
            }
            if valid_children:
                sym_data["children"] = valid_children
            return sym_data

        symbols = []
        for i, decl in enumerate(file_decls):
            d_line = max(0, decl.line - 1)
            d_col = max(0, decl.col - 1)

            next_start = file_decls[i + 1].line - 1 if i + 1 < len(file_decls) else total_lines
            end_line = min(total_lines - 1, max(d_line, next_start - 1)) if total_lines else 0
            while end_line > d_line and lines and not lines[end_line].strip():
                end_line -= 1

            if isinstance(decl, FuncDecl):
                kind = SymbolKind.Method if decl.owner else SymbolKind.Function
                name = f"{_shown_ty(decl.owner)}.{decl.name}" if decl.owner else decl.name
                params_str = ", ".join(p.name for p in decl.params)
                detail = f"({params_str})" + (f" -> {format_type(decl.ret)}" if decl.ret else "")
                sym = build_symbol(name, detail, kind, d_line, d_col, end_line)
                if sym:
                    symbols.append(sym)

            elif isinstance(decl, StructDecl):
                children = []
                for f in decl.fields:
                    f_line = max(0, f.line - 1)
                    f_col = max(0, f.col - 1)
                    f_sym = build_symbol(f.name, format_type(f.type_ref), SymbolKind.Field, f_line, f_col, f_line)
                    if f_sym:
                        children.append(f_sym)
                sym = build_symbol(decl.name, "struct", SymbolKind.Struct, d_line, d_col, end_line, children)
                if sym:
                    symbols.append(sym)

            elif isinstance(decl, EnumDecl):
                children = []
                for v in decl.variants:
                    v_line = max(0, v.line - 1)
                    v_col = max(0, v.col - 1)
                    v_detail = f"({', '.join(format_type(p) for p in v.payload)})" if v.payload else ""
                    v_sym = build_symbol(v.name, v_detail, SymbolKind.EnumMember, v_line, v_col, v_line)
                    if v_sym:
                        children.append(v_sym)
                sym = build_symbol(decl.name, "enum", SymbolKind.Enum, d_line, d_col, end_line, children)
                if sym:
                    symbols.append(sym)

            elif isinstance(decl, FeatureDecl):
                children = []
                for m in decl.methods:
                    m_line = max(0, m.line - 1)
                    m_col = max(0, m.col - 1)
                    m_detail = f"({', '.join(p.name for p in m.params)})" + (f" -> {format_type(m.ret)}" if m.ret else "")
                    m_sym = build_symbol(m.name, m_detail, SymbolKind.Method, m_line, m_col, m_line)
                    if m_sym:
                        children.append(m_sym)
                sym = build_symbol(decl.name, "feature", SymbolKind.Interface, d_line, d_col, end_line, children)
                if sym:
                    symbols.append(sym)

            elif isinstance(decl, ConstDecl):
                sym = build_symbol(decl.name, format_type(decl.type_ref) if decl.type_ref else "const", SymbolKind.Constant, d_line, d_col, end_line)
                if sym:
                    symbols.append(sym)

            elif isinstance(decl, ExternFuncDecl):
                params_str = ", ".join(p.name for p in decl.params)
                detail = f"({params_str})" + (f" -> {format_type(decl.ret)}" if decl.ret else "")
                sym = build_symbol(decl.name, f"extern fn{detail}", SymbolKind.Function, d_line, d_col, end_line)
                if sym:
                    symbols.append(sym)

        return symbols

    # --- Completion (Otomatik Tamamlama) -------------------------------------

    def m_textDocument_completion(self, params: dict[str, Any]) -> dict[str, Any]:
        uri = params.get("textDocument", {}).get("uri")
        pos = params.get("position", {})
        line_0 = pos.get("line", 0)
        char_0 = pos.get("character", 0)

        analysis = self.analysis.get(uri)
        source = analysis.source if analysis else self.documents.get(uri, "")
        lines = source.splitlines()
        line_text = lines[line_0] if 0 <= line_0 < len(lines) else ""
        prefix_line = line_text[:char_0]
        suffix_line = line_text[char_0:]
        has_open_paren = suffix_line.lstrip().startswith("(")

        def func_insert(name: str, has_params: bool) -> tuple[str, int]:
            if has_open_paren:
                return name, InsertTextFormat.PlainText
            if has_params:
                return f"{name}($0)", InsertTextFormat.Snippet
            return f"{name}()$0", InsertTextFormat.Snippet

        items: list[dict[str, Any]] = []
        seen_labels: set[str] = set()

        def add_item(item: dict[str, Any]) -> None:
            lbl = item["label"]
            if lbl not in seen_labels:
                seen_labels.add(lbl)
                items.append(item)

        # 0. `import <module>` / `import "<file>"`: every module that can be imported from here
        imp = re.match(r'^(\s*import\s+)(?:"([^"]*)|([A-Za-z_][A-Za-z0-9_.]*)?)$', prefix_line)
        if imp:
            return {"isIncomplete": False,
                    "items": _import_completions(uri_to_path(uri), line_0, char_0,
                                                 imp.group(2), imp.group(3) or "")}
        trigger = (params.get("context") or {}).get("triggerCharacter")
        if trigger in (" ", '"'):  # only registered for `import`; elsewhere stay silent as before
            return {"isIncomplete": False, "items": []}

        # 1. Check if inside comment (#) or string literal ('...', "...")
        in_str = False
        quote_char = ""
        in_comment = False
        i = 0
        while i < char_0 and i < len(line_text):
            ch = line_text[i]
            if in_str:
                if ch == "\\":
                    i += 2
                    continue
                elif ch == quote_char:
                    in_str = False
            else:
                if ch == "#":
                    in_comment = True
                    break
                elif ch in ('"', "'"):
                    in_str = True
                    quote_char = ch
            i += 1

        if in_comment or in_str:
            return {"isIncomplete": False, "items": []}

        # 2. Do not suggest completions while writing number literals (e.g. 123, 3.14)
        if re.search(r'\b\d+(?:\.\d*)?$', prefix_line):
            return {"isIncomplete": False, "items": []}

        # 2b. `@` at the start of a line: the attributes declared in the program
        if re.match(r"\s*@\w*$", prefix_line):
            from .ast_nodes import AttrDecl
            for d in (analysis.program.decls if analysis and analysis.program else ()):
                if not isinstance(d, AttrDecl):
                    continue
                sig = ", ".join(f"{p.name}: {p.kind}" + (" = ..." if p.default is not None else "")
                                for p in d.params)
                on = f" on {', '.join(d.targets)}" if d.targets else ""
                required = [p for p in d.params if p.default is None]
                add_item({
                    "label": d.name,
                    "kind": CompletionItemKind.Property,
                    "detail": f"attribute {d.name}({sig}){on}",
                    "insertText": f"{d.name}($0)" if required else d.name,
                    "insertTextFormat": InsertTextFormat.Snippet,
                })
            return {"isIncomplete": False, "items": items}

        # 3. Member / method completion after dot (.)
        if prefix_line.endswith("."):
            receiver_match = re.search(r'([A-Za-z_][A-Za-z0-9_]*)\.$', prefix_line)
            receiver_name = receiver_match.group(1) if receiver_match else ""

            # Standard built-in properties
            add_item({
                "label": "len",
                "kind": CompletionItemKind.Property,
                "detail": "usize",
                "documentation": "Returns collection or string length.",
            })
            ins_value_or_panic, fmt_value_or_panic = func_insert("value_or_panic", False)
            add_item({
                "label": "value_or_panic()",
                "kind": CompletionItemKind.Method,
                "detail": "fn value_or_panic(self) -> T",
                "documentation": "Extracts Optional or Result value, panics otherwise.",
                "insertText": ins_value_or_panic,
                "insertTextFormat": fmt_value_or_panic,
            })
            ins_value_or, fmt_value_or = func_insert("value_or", True)
            add_item({
                "label": "value_or()",
                "kind": CompletionItemKind.Method,
                "detail": "fn value_or(self, fallback: T) -> T",
                "documentation": "Extracts Optional or Result value, returns default otherwise.",
                "insertText": ins_value_or,
                "insertTextFormat": fmt_value_or,
            })
            for m_name in ["has_value", "is_none", "is_ok", "is_err"]:
                ins_m, fmt_m = func_insert(m_name, False)
                add_item({
                    "label": f"{m_name}()",
                    "kind": CompletionItemKind.Method,
                    "detail": f"fn {m_name}(self) -> bool",
                    "insertText": ins_m,
                    "insertTextFormat": fmt_m,
                })

            # Infer receiver type
            target_struct_name: Optional[str] = None
            if analysis and analysis.program and receiver_name:
                total_lines = len(lines)
                enclosing = _find_enclosing_func(analysis.program.decls, line_0 + 1, total_lines)
                if enclosing:
                    locals_in_scope = _collect_local_symbols(enclosing, line_0 + 1)
                    matching = [s for s in locals_in_scope if s.name == receiver_name]
                    if matching:
                        sym = matching[-1]
                        if isinstance(sym.node, Param) and sym.node.type_ref:
                            target_struct_name = sym.node.type_ref.name
                        elif isinstance(sym.node, VarDecl):
                            if sym.node.type_ref:
                                target_struct_name = sym.node.type_ref.name
                            elif sym.node.ty:
                                target_struct_name = sym.node.ty

            # Add struct fields and methods from AST
            has_ast_structs = False
            if analysis and analysis.program:
                for decl in analysis.program.decls:
                    if isinstance(decl, StructDecl):
                        if not target_struct_name or decl.name == target_struct_name:
                            for f in decl.fields:
                                has_ast_structs = True
                                add_item({
                                    "label": f.name,
                                    "kind": CompletionItemKind.Field,
                                    "detail": f"{decl.name}.{f.name}: {format_type(f.type_ref)}" if not target_struct_name else format_type(f.type_ref),
                                })
                    if isinstance(decl, FuncDecl) and decl.owner:
                        if not target_struct_name or decl.owner == target_struct_name:
                            has_ast_structs = True
                            has_p = len(decl.params) > 1  # parameters other than self
                            ins_m, fmt_m = func_insert(decl.name, has_p)
                            add_item({
                                "label": decl.name,
                                "kind": CompletionItemKind.Method,
                                "detail": f"fn {_shown_ty(decl.owner)}.{decl.name}(...)",
                                "insertText": ins_m,
                                "insertTextFormat": fmt_m,
                            })

            # Regex-assisted search over source text (if AST is not ready yet while typing)
            if not has_ast_structs or not target_struct_name:
                struct_defs: dict[str, list[tuple[str, str]]] = {}
                cur_s = None
                for l_src in source.splitlines():
                    sm = re.match(r'^\s*struct\s+([A-Za-z_][A-Za-z0-9_]*)\b', l_src)
                    if sm:
                        cur_s = sm.group(1)
                        struct_defs[cur_s] = []
                        continue
                    if cur_s:
                        fm = re.match(r'^\s*([A-Za-z_][A-Za-z0-9_]*)\s*:\s*([A-Za-z0-9_\[\], ]+)', l_src)
                        if fm and fm.group(1) not in KEYWORDS:
                            struct_defs[cur_s].append((fm.group(1), fm.group(2).strip()))
                        elif l_src.strip() and not l_src.startswith(" ") and not l_src.startswith("\t"):
                            cur_s = None

                # Infer receiver type
                t_guess = target_struct_name or receiver_name
                if not target_struct_name and receiver_name:
                    vm = re.search(r'\b' + re.escape(receiver_name) + r'\s*=\s*([A-Za-z_][A-Za-z0-9_]*)\s*\(', source)
                    if not vm:
                        vm = re.search(r'\b' + re.escape(receiver_name) + r'\s*:\s*(?:consume\s+|read\s+|lend\s+)?([A-Za-z_][A-Za-z0-9_]*)', source)
                    if vm:
                        t_guess = vm.group(1)

                if t_guess and t_guess in struct_defs:
                    for f_name, f_ty in struct_defs[t_guess]:
                        add_item({
                            "label": f_name,
                            "kind": CompletionItemKind.Field,
                            "detail": f_ty,
                        })
                else:
                    for s_name, fields in struct_defs.items():
                        for f_name, f_ty in fields:
                            add_item({
                                "label": f_name,
                                "kind": CompletionItemKind.Field,
                                "detail": f"{s_name}.{f_name}: {f_ty}",
                            })

            return {"isIncomplete": False, "items": items}

        stripped_prefix = prefix_line.rstrip()

        # 4. Block-initiating ':' characters
        # fn main():, if cond:, elif cond:, else:, while cond:, for x in y:, match x:, struct S:, enum E:, feature T:, impl ...:
        # ':' after closing parenthesis or at the end of block-opening lines
        # In these cases the block has started and expression is terminated on this line; do NOT suggest types or code.
        if stripped_prefix.endswith(":"):
            if (
                re.search(r'\)\s*(?:->\s*[^:]+)?:\s*$', stripped_prefix)
                or re.search(r'^\s*(?:if|elif|else|while|for|match|case|loop|struct|enum|feature|impl)\b.*:\s*$', stripped_prefix)
                or re.search(r'^\s*:\s*$', stripped_prefix)
            ):
                return {"isIncomplete": False, "items": []}

        # 5. Type Completion: Only where a type is genuinely expected
        # - Return type: after `->` (e.g. `fn foo() -> `)
        # - Variable type: `x:`, `const X:`, `let x:`
        # - Parameter type: inside open paren after parameter name and ':' (e.g. `fn foo(x:`)
        # - Struct field type: in struct body `field:`
        # - Generic bound: `[T:`
        is_type_context = False
        if re.search(r'->\s*$', prefix_line):
            is_type_context = True
        elif stripped_prefix.endswith(":"):
            if re.search(r'^\s*(?:var|const|let)\s+(?:mut\s+)?[A-Za-z_][A-Za-z0-9_]*\s*:\s*$', stripped_prefix):
                is_type_context = True
            elif re.search(r'\([^)]*\b[A-Za-z_][A-Za-z0-9_]*\s*:\s*$', stripped_prefix):
                is_type_context = True
            elif re.search(r'\[[^\]]*\b[A-Za-z_][A-Za-z0-9_]*\s*:\s*$', stripped_prefix):
                is_type_context = True
            elif re.search(r'^\s+[A-Za-z_][A-Za-z0-9_]*\s*:\s*$', stripped_prefix):
                first_w = stripped_prefix.strip().split(":")[0].strip()
                if first_w not in KEYWORDS:
                    is_type_context = True

        if is_type_context:
            for prim, doc in PRIMITIVE_DOCS.items():
                add_item({
                    "label": prim,
                    "kind": CompletionItemKind.Class,
                    "detail": "primitive type",
                    "documentation": doc,
                })
            for t_name in ["Optional", "Result", "Box", "List"]:
                if t_name in BUILTIN_DOCS:
                    add_item({
                        "label": t_name,
                        "kind": CompletionItemKind.Class,
                        "detail": "built-in type",
                        "documentation": BUILTIN_DOCS[t_name],
                    })
            for m_kw in ["consume", "read", "lend"]:
                add_item({
                    "label": m_kw,
                    "kind": CompletionItemKind.Keyword,
                    "detail": "referans/sahiplik modu",
                    "documentation": KEYWORD_DOCS.get(m_kw, ""),
                })
            has_types = False
            if analysis and analysis.program:
                for decl in analysis.program.decls:
                    if isinstance(decl, StructDecl):
                        has_types = True
                        add_item({"label": decl.name, "kind": CompletionItemKind.Struct, "detail": f"struct {decl.name}"})
                    elif isinstance(decl, EnumDecl):
                        has_types = True
                        add_item({"label": decl.name, "kind": CompletionItemKind.Enum, "detail": f"enum {decl.name}"})
                    elif isinstance(decl, FeatureDecl):
                        has_types = True
                        add_item({"label": decl.name, "kind": CompletionItemKind.Interface, "detail": f"feature {decl.name}"})
            if not has_types:
                for l_src in source.splitlines():
                    sm = re.match(r'^\s*(?:struct|enum|feature)\s+([A-Za-z_][A-Za-z0-9_]*)', l_src)
                    if sm:
                        add_item({"label": sm.group(1), "kind": CompletionItemKind.Class, "detail": "user type"})
            return {"isIncomplete": False, "items": items}

        # If line ends with ':' but is not a valid type context, return empty
        if stripped_prefix.endswith(":"):
            return {"isIncomplete": False, "items": []}

        # 6. After Terminated Expression
        # If space is left after a literal or closing paren and no new operator yet:
        # Example: `let x = false `, `return true `, `123 `, `"text" `, `(a + b) `
        if re.search(r'(?:\b(?:false|true|nil|break|continue|pass)\b|\d+|["\'][^"\']*["\']|[)\]}])\s+$', prefix_line):
            return {"isIncomplete": False, "items": []}

        # 7. General Code Completion: Local Variables, Keywords, Types, Functions
        all_items: list[dict[str, Any]] = []
        all_seen: set[str] = set()

        def add_cand(item: dict[str, Any]) -> None:
            lbl = item["label"]
            if lbl not in all_seen:
                all_seen.add(lbl)
                all_items.append(item)

        if analysis and analysis.program:
            total_lines = len(lines)
            enclosing = _find_enclosing_func(analysis.program.decls, line_0 + 1, total_lines)
            if enclosing:
                locals_in_scope = _collect_local_symbols(enclosing, line_0 + 1)
                for sym in locals_in_scope:
                    add_cand({
                        "label": sym.name,
                        "kind": CompletionItemKind.Variable,
                        "detail": sym.display,
                    })

        for kw in sorted(KEYWORDS):
            add_cand({
                "label": kw,
                "kind": CompletionItemKind.Keyword,
                "detail": "anahtar kelime",
            })

        for label, insert, detail in (
            ("overflow: wrap", "overflow: wrap", "taÅŸma: sarmalama"),
            ("overflow: trap", "overflow: trap", "taÅŸma: tuzak"),
            ("wrapping", "wrapping:\n    ", "sarmalayan aritmetik bloÄŸu"),
            ("range", "range ", "for i in range n"),
        ):
            add_cand({
                "label": label,
                "kind": CompletionItemKind.Keyword,
                "detail": detail,
                "documentation": KEYWORD_DOCS.get(label.split(":", 1)[0].strip(), ""),
                "insertText": insert,
                "insertTextFormat": InsertTextFormat.PlainText,
                "filterText": label.split(":", 1)[0].strip(),
            })
        for op in (
            "wrapping_add", "wrapping_sub", "wrapping_mul",
            "saturating_add", "saturating_sub", "saturating_mul",
            "checked_add", "checked_sub", "checked_mul",
        ):
            add_cand({
                "label": op,
                "kind": CompletionItemKind.Operator,
                "detail": "taÅŸma aritmetiÄŸi",
                "documentation": BUILTIN_DOCS.get(op, ""),
                "insertText": op + " ",
                "insertTextFormat": InsertTextFormat.PlainText,
            })

        for prim, doc in PRIMITIVE_DOCS.items():
            add_cand({
                "label": prim,
                "kind": CompletionItemKind.Class,
                "detail": "primitive type",
                "documentation": doc,
            })

        for name, doc in BUILTIN_DOCS.items():
            is_func = "(" in doc and not name.startswith("Optional") and not name.startswith("Result") and name != "None"
            kind = CompletionItemKind.Function if is_func else CompletionItemKind.Class
            if is_func:
                has_p = not ("()" in doc or "(void)" in doc)
                ins_fn, fmt_fn = func_insert(name, has_p)
                add_cand({
                    "label": name,
                    "kind": kind,
                    "detail": "built-in / prelude",
                    "documentation": doc,
                    "insertText": ins_fn,
                    "insertTextFormat": fmt_fn,
                })
            else:
                add_cand({
                    "label": name,
                    "kind": kind,
                    "detail": "built-in / prelude",
                    "documentation": doc,
                })

        funcs_from_ast = False
        if analysis and analysis.program:
            for decl in analysis.program.decls:
                if isinstance(decl, FuncDecl) and not decl.owner:
                    funcs_from_ast = True
                    params_str = ", ".join(p.name for p in decl.params)
                    has_p = len(decl.params) > 0
                    ins_fn, fmt_fn = func_insert(decl.name, has_p)
                    add_cand({
                        "label": decl.name,
                        "kind": CompletionItemKind.Function,
                        "detail": f"fn ({params_str})" + (f" -> {format_type(decl.ret)}" if decl.ret else ""),
                        "insertText": ins_fn,
                        "insertTextFormat": fmt_fn,
                    })
                elif isinstance(decl, StructDecl):
                    add_cand({
                        "label": decl.name,
                        "kind": CompletionItemKind.Struct,
                        "detail": f"struct {decl.name}",
                    })
                elif isinstance(decl, EnumDecl):
                    add_cand({
                        "label": decl.name,
                        "kind": CompletionItemKind.Enum,
                        "detail": f"enum {decl.name}",
                    })
                    for v in decl.variants:
                        add_cand({
                            "label": v.name,
                            "kind": CompletionItemKind.EnumMember,
                            "detail": f"{decl.name}.{v.name}",
                        })
                elif isinstance(decl, FeatureDecl):
                    add_cand({
                        "label": decl.name,
                        "kind": CompletionItemKind.Interface,
                        "detail": f"feature {decl.name}",
                    })
                elif isinstance(decl, ConstDecl):
                    add_cand({
                        "label": decl.name,
                        "kind": CompletionItemKind.Constant,
                        "detail": f"const {decl.name}",
                    })
                elif isinstance(decl, ExternFuncDecl):
                    params_str = ", ".join(p.name for p in decl.params)
                    has_p = len(decl.params) > 0
                    ins_fn, fmt_fn = func_insert(decl.name, has_p)
                    add_cand({
                        "label": decl.name,
                        "kind": CompletionItemKind.Function,
                        "detail": f"extern fn ({params_str})" + (f" -> {format_type(decl.ret)}" if decl.ret else ""),
                        "insertText": ins_fn,
                        "insertTextFormat": fmt_fn,
                    })

        # Regex-assisted function search over source text (if AST is not ready yet while typing)
        if not funcs_from_ast:
            for l_src in source.splitlines():
                fm = re.match(r'^\s*fn\s+([A-Za-z_][A-Za-z0-9_]*)\s*(?:\[[^\]]*\])?\s*\(([^)]*)\)', l_src)
                if fm:
                    f_name = fm.group(1)
                    f_params = fm.group(2).strip()
                    has_p = len(f_params) > 0
                    ins_fn, fmt_fn = func_insert(f_name, has_p)
                    add_cand({
                        "label": f_name,
                        "kind": CompletionItemKind.Function,
                        "detail": f"fn ({f_params})",
                        "insertText": ins_fn,
                        "insertTextFormat": fmt_fn,
                    })

        # 8. Smart Filtering and Termination Check Based on Word Under Cursor
        cur_word_match = re.search(r'([A-Za-z_][A-Za-z0-9_]*)$', prefix_line)
        cur_word = cur_word_match.group(1) if cur_word_match else ""

        if cur_word:
            prefix_matches = [it for it in all_items if it["label"].startswith(cur_word)]
            exact_matches = [it for it in prefix_matches if it["label"] == cur_word]
            longer_matches = [it for it in prefix_matches if len(it["label"]) > len(cur_word)]

            # If user completely typed a keyword, type or symbol (e.g. 'false', 'true', 'return'):
            if exact_matches:
                # If there are no longer candidates (e.g. no other candidate for 'false'),
                # the word and expression are complete; return empty list to close suggestion.
                if not longer_matches:
                    return {"isIncomplete": False, "items": []}
                # If longer alternatives exist (e.g. 'in' typed but 'int', 'input' also exist),
                # remove exact match user already typed and only offer longer ones.
                return {"isIncomplete": False, "items": longer_matches}

            return {"isIncomplete": False, "items": prefix_matches if prefix_matches else all_items}

        return {"isIncomplete": False, "items": all_items}

    # --- Formatting (Document Formatting) --------------------------------------

    def m_textDocument_formatting(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        uri = params.get("textDocument", {}).get("uri")
        analysis = self.analysis.get(uri)
        source = analysis.source if analysis else self.documents.get(uri, "")
        if not source:
            return []

        formatted = format_greengold_source(source)
        if formatted == source:
            return []

        lines = source.splitlines()
        last_line = max(0, len(lines) - 1)
        last_char = len(lines[last_line]) if lines else 0

        return [{
            "range": {
                "start": {"line": 0, "character": 0},
                "end": {"line": last_line, "character": last_char},
            },
            "newText": formatted,
        }]

    # --- Signature Help ---------------------------------------

    def m_textDocument_signatureHelp(self, params: dict[str, Any]) -> Optional[dict[str, Any]]:
        uri = params.get("textDocument", {}).get("uri")
        pos = params.get("position", {})
        line_0 = pos.get("line", 0)
        char_0 = pos.get("character", 0)

        analysis = self.analysis.get(uri)
        source = analysis.source if analysis else self.documents.get(uri, "")
        lines = source.splitlines()
        if not (0 <= line_0 < len(lines)):
            return None

        line_text = lines[line_0][:char_0]

        # Scan parens and strings forward to find unclosed call
        stack: list[tuple[str, int]] = []
        i = 0
        n = len(line_text)
        in_str: Optional[str] = None

        while i < n:
            ch = line_text[i]
            if in_str:
                if ch == "\\":
                    i += 2
                    continue
                if ch == in_str:
                    in_str = None
                i += 1
                continue

            if ch in ('"', "'"):
                in_str = ch
                i += 1
                continue

            if ch == "(":
                j = i - 1
                while j >= 0 and line_text[j] in " \t":
                    j -= 1
                end_ident = j + 1
                while j >= 0 and (line_text[j].isalnum() or line_text[j] in "._"):
                    j -= 1
                start_ident = j + 1
                ident = line_text[start_ident:end_ident].strip()
                if ident:
                    stack.append((ident, 0))
                else:
                    stack.append(("", 0))
            elif ch == ",":
                if stack:
                    ident, param_idx = stack[-1]
                    stack[-1] = (ident, param_idx + 1)
            elif ch == ")":
                if stack:
                    stack.pop()
            i += 1

        if not stack or not stack[-1][0]:
            return None

        callee, active_param = stack[-1]
        base_callee = callee.split(".")[-1]

        # Search function in AST
        if analysis and analysis.program:
            for decl in analysis.program.decls:
                if isinstance(decl, FuncDecl) and (decl.name == callee or decl.name == base_callee):
                    params_info = []
                    for p in decl.params:
                        params_info.append({"label": f"{p.name}: {format_type(p.type_ref)}"})
                    owner_prefix = f"{_shown_ty(decl.owner)}." if decl.owner else ""
                    sig_label = f"fn {owner_prefix}{decl.name}(" + ", ".join(p["label"] for p in params_info) + ")"
                    if decl.ret:
                        sig_label += f" -> {format_type(decl.ret)}"
                    return {
                        "signatures": [{
                            "label": sig_label,
                            "parameters": params_info,
                        }],
                        "activeSignature": 0,
                        "activeParameter": active_param,
                    }
                elif isinstance(decl, ExternFuncDecl) and (decl.name == callee or decl.name == base_callee):
                    params_info = []
                    for p in decl.params:
                        params_info.append({"label": f"{p.name}: {format_type(p.type_ref)}"})
                    sig_label = f"extern fn {decl.name}(" + ", ".join(p["label"] for p in params_info) + ")"
                    if decl.ret:
                        sig_label += f" -> {format_type(decl.ret)}"
                    return {
                        "signatures": [{
                            "label": sig_label,
                            "parameters": params_info,
                        }],
                        "activeSignature": 0,
                        "activeParameter": active_param,
                    }

        if base_callee in BUILTIN_DOCS:
            return {
                "signatures": [{
                    "label": f"{base_callee}(...)",
                    "documentation": BUILTIN_DOCS[base_callee],
                    "parameters": [{"label": "args"}],
                }],
                "activeSignature": 0,
                "activeParameter": active_param,
            }

        # Search in source text (if AST is not ready yet while typing)
        fn_pattern = r'fn\s+(?:[A-Za-z0-9_]+\.)?' + re.escape(base_callee) + r'(?:\[[^\]]*\])?\s*\(([^)]*)\)(?:\s*->\s*([A-Za-z0-9_\[\], ]+))?:'
        fm = re.search(fn_pattern, source)
        if fm:
            raw_params = fm.group(1).strip()
            ret_type = fm.group(2)
            params_info = []
            if raw_params:
                for p_str in raw_params.split(","):
                    p_str = p_str.strip()
                    if p_str:
                        params_info.append({"label": p_str})
            sig_label = f"fn {base_callee}(" + ", ".join(p["label"] for p in params_info) + ")"
            if ret_type:
                sig_label += f" -> {ret_type.strip()}"
            return {
                "signatures": [{
                    "label": sig_label,
                    "parameters": params_info,
                }],
                "activeSignature": 0,
                "activeParameter": active_param,
            }

        return None

    # --- Find All References (Shift+F12) -------------------------------------

    def m_textDocument_references(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        uri = params.get("textDocument", {}).get("uri")
        pos = params.get("position", {})
        line_0 = pos.get("line", 0)
        char_0 = pos.get("character", 0)

        analysis = self.analysis.get(uri)
        if not analysis:
            return []

        word, start_c, end_c = self._word_at(analysis.source, line_0, char_0)
        if not word or not word.isidentifier() or word in KEYWORDS or word in PRIMS:
            return []

        # Determine scope: is word a local variable or parameter inside a function?
        line_1 = line_0 + 1
        is_local = False
        local_fn: Optional[FuncDecl] = None

        if analysis.program:
            for decl in analysis.program.decls:
                if isinstance(decl, FuncDecl):
                    fn_start = getattr(decl, "line", 0)
                    # Check if word is a parameter or declared local in this function
                    has_param = any(p.name == word for p in decl.params)
                    has_local_var = False
                    for stmt in decl.body:
                        if isinstance(stmt, VarDecl) and stmt.name == word:
                            has_local_var = True
                            break
                        if isinstance(stmt, Binding) and any(n == word for n in stmt.names):
                            has_local_var = True
                            break
                        if isinstance(stmt, For) and (stmt.var_name == word or stmt.index_name == word):
                            has_local_var = True
                            break

                    if (has_param or has_local_var):
                        # Approximate function body range
                        fn_end = 999999
                        for other in analysis.program.decls:
                            o_line = getattr(other, "line", 0)
                            if o_line > fn_start and o_line < fn_end:
                                fn_end = o_line
                        if fn_start <= line_1 < fn_end:
                            is_local = True
                            local_fn = decl
                            break

        results: list[dict[str, Any]] = []
        seen = set()

        def add_token_match(target_uri: str, token: Token) -> None:
            key = (target_uri, token.line - 1, token.col - 1)
            if key not in seen:
                seen.add(key)
                results.append({
                    "uri": target_uri,
                    "range": {
                        "start": {"line": token.line - 1, "character": token.col - 1},
                        "end": {"line": token.line - 1, "character": token.col - 1 + token.length},
                    },
                })

        if is_local and local_fn is not None:
            fn_start_line = local_fn.line
            fn_end_line = 999999
            if analysis.program:
                for d in analysis.program.decls:
                    d_line = getattr(d, "line", 0)
                    if d_line > fn_start_line and d_line < fn_end_line:
                        fn_end_line = d_line
            for t in analysis.tokens:
                if fn_start_line <= t.line < fn_end_line and t.text == word and t.kind == "NAME":
                    add_token_match(uri, t)
        else:
            # Global symbol or method/field: search across all analyzed open documents
            for doc_uri, doc_analysis in self.analysis.items():
                for t in doc_analysis.tokens:
                    if t.text == word and (t.kind == "NAME" or t.text == word):
                        add_token_match(doc_uri, t)

        return results

    # --- Rename Symbol (F2) --------------------------------------------------

    def m_textDocument_prepareRename(self, params: dict[str, Any]) -> Optional[dict[str, Any]]:
        uri = params.get("textDocument", {}).get("uri")
        pos = params.get("position", {})
        line_0 = pos.get("line", 0)
        char_0 = pos.get("character", 0)

        analysis = self.analysis.get(uri)
        if not analysis:
            return None

        word, start_c, end_c = self._word_at(analysis.source, line_0, char_0)
        if not word or not word.isidentifier():
            return None
        if word in KEYWORDS or word in PRIMS or word in BUILTINS or word in PRELUDE_NAMES:
            return None

        return {
            "range": {
                "start": {"line": line_0, "character": start_c},
                "end": {"line": line_0, "character": end_c},
            },
            "placeholder": word,
        }

    def m_textDocument_rename(self, params: dict[str, Any]) -> dict[str, Any]:
        uri = params.get("textDocument", {}).get("uri")
        new_name = (params.get("newName") or "").strip()

        if not new_name or not new_name.isidentifier() or new_name in KEYWORDS:
            return {"changes": {}}

        refs = self.m_textDocument_references({
            "textDocument": {"uri": uri},
            "position": params.get("position", {}),
            "context": {"includeDeclaration": True},
        })

        changes: dict[str, list[dict[str, Any]]] = {}
        for r in refs:
            doc_uri = r["uri"]
            if doc_uri not in changes:
                changes[doc_uri] = []
            changes[doc_uri].append({
                "range": r["range"],
                "newText": new_name,
            })

        return {"changes": changes}

    # --- Workspace Symbols (Ctrl+T) ------------------------------------------

    def m_workspace_symbol(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        query = (params.get("query") or "").lower()
        results: list[dict[str, Any]] = []

        for uri, analysis in self.analysis.items():
            if not analysis.program:
                continue
            for decl in analysis.program.decls:
                name = getattr(decl, "name", None)
                if not name:
                    continue
                if query and query not in name.lower():
                    continue

                kind = SymbolKind.Variable
                if isinstance(decl, FuncDecl):
                    kind = SymbolKind.Function
                elif isinstance(decl, StructDecl):
                    kind = SymbolKind.Struct
                elif isinstance(decl, EnumDecl):
                    kind = SymbolKind.Enum
                elif isinstance(decl, FeatureDecl):
                    kind = SymbolKind.Interface
                elif isinstance(decl, ConstDecl):
                    kind = SymbolKind.Constant

                d_line = max(0, getattr(decl, "line", 1) - 1)
                d_col = max(0, getattr(decl, "col", 1) - 1)
                results.append({
                    "name": name,
                    "kind": kind,
                    "location": {
                        "uri": uri,
                        "range": {
                            "start": {"line": d_line, "character": d_col},
                            "end": {"line": d_line, "character": d_col + len(name)},
                        },
                    },
                })
                if len(results) >= 100:
                    return results

        return results


def run_server() -> int:
    """Starts LSP server from command line."""
    server = LanguageServer()
    return server.run()


if __name__ == "__main__":
    sys.exit(run_server())
