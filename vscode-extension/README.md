# Greengold Language Support for VS Code

This official VS Code extension provides a full, first-class IDE experience for the **Greengold (.gg)** systems programming language.

In addition to syntax highlighting and modern snippets, it provides an interactive **Test Explorer**, **CodeLens** inline actions, **native debugging (DAP)**, **build tasks & problem matchers**, and a rich **LSP (Language Server Protocol)** server with real-time diagnostics, go to definition, find all references, symbol renaming, hover information, inlay hints, code completion, and automatic formatting.

---

## 🚀 Key Features

### 1. Language Server Protocol (LSP) Support
The extension automatically launches the Greengold LSP server (`gg lsp`) in the background.

- **🔴 Real-Time Diagnostics:**
  - Displays red squiggly underlines for syntax, type mismatch, scoping, and move/borrow errors while typing (`didChange`) and saving (`didSave`).
  - Lists error messages, file locations, and "how to fix" hints in the "Problems" panel.
- **🔍 Go to Definition (`F12` / `Ctrl+Click`):**
  - Function & method calls -> Jumps to definition.
  - Struct, Enum, and Feature types -> Jumps to declaration.
  - Variables & parameters -> Jumps to local declaration.
  - Module imports (`import "helper.gg"` / `import std.thread`) -> Jumps directly to the imported file.
- **🔎 Find All References (`Shift+F12`):**
  - Instant project-wide and file-wide symbol search for functions, structs, enums, fields, and variables.
- **✏️ Rename Symbol (`F2`):**
  - Safely renames functions, local variables, parameters, and types with live preview across the workspace.
- **🌐 Workspace Symbol Search (`Ctrl+T`):**
  - Quickly search and jump to any declared struct, enum, function, or constant across the entire workspace.
- **💡 Hover Information:**
  - Full signatures when hovering over functions (`fn add(a: i32, b: i32) -> i32`).
  - Fields, signatures, and types when hovering over Structs and Features.
  - Variants and payload types when hovering over Enums.
  - Semantic explanations and example code blocks when hovering over keywords (`public`, `private`, `fixed`, `consume`, `lend`, `read`, `exclusive`, `soa`, `tied to`, `match`, `defer`, `feature`, `unsafe`, `comptime`, `hot`, `trust`, `require`, `test`, `overflow`, `wrapping`).
  - Explanations for primitive types (`i32`, `usize`, `f64`, `bool`, `str`) and prelude items (`Optional`, `Result`, `Valid`, `None`, `Ok`, `Err`, `Box`, `List`, `string`, `print`, `panic`, `input`).
- **👁 Inlay Hints:**
  - Inferred parameter modes appear in the signature: `fn add(xs: lend List[i32])` when `lend` was left out.
  - Bindings written with `=` (and `const`, loop variables, pattern names) show the type the compiler found. On `=` the type sits between the two characters (`k: i32 = 3`); elsewhere it follows the name (`for e: read Entity in ents:`).
  - A variable that nothing changes is treated as `fixed`, and the word appears in front of it: `fixed k = 3`. Changing the variable anywhere makes the hint go away.
  - A capturing lambda shows how it holds each variable: `fn [lend out](x: i32)`.
  - Modes and types already written in the source are not repeated. Hide the hints with `"editor.inlayHints.enabled": "off"`.
- **🌳 Document Symbols & Outline (`Ctrl+Shift+O`):**
  - Hierarchically lists functions, methods, structs (with fields), features, enums (with variants), and constants in the VS Code Outline panel and breadcrumbs.
- **✨ Intelligent Code Completion (IntelliSense):**
  - Triggered on dot (`.`): Struct fields, receiver methods (`.len`, `.value_or_panic()`, `.push()`, `.pop()`, `.get()`, etc.).
  - General typing: Keywords, local variables, functions, types, and prelude items.
- **🪄 Document Formatting (`Shift+Alt+F`):**
  - Aligns indentation to standard 4 spaces, adjusts operator and comma spacing, and cleans up redundant whitespace.
- **📝 Signature Help:**
  - Displays parameter lists and bolds the current parameter when typing `(` or `,` during function calls.

---

### 2. 🧪 Interactive Test Explorer (`vscode.TestController`)

Greengold unit tests (`test name:` blocks and `fn test_*():`) are integrated directly into VS Code's native Testing panel:
- **Automatic Test Discovery:** Detects `test` / `test name:` blocks and `fn test_*():` functions. A block's name is the one `gg test` reports (`add.test`, `add.negatives`).
- **Editor Gutter Run Icons:** Click the green play icon next to any test function in the editor margin to run it individually.
- **Test Explorer Tree View:** View all tests grouped by file in the Activity Bar Testing panel.
- **Real-Time Results:** Runs `gg test --json` once per file and maps each test's `status` and `message`.

---

### 3. 👓 CodeLens Inline Actions

Quick-action links appear directly above functions in the editor:
- Above `fn main():`:
  - `[▶ Run]` -> `gg run` on this file.
  - `[⚡ Release]` -> Run with LLVM -O3 optimizations.
  - `[🐞 Debug]` -> Compile binary with debug symbols and launch native debugger.
- Above a `test` block or `fn test_*():`:
  - `[▶ Run Test]` -> Runs `gg test` on that file. The Testing panel reports each test from `gg test --json`.

---

### 4. 🐞 Native Debugging Support (DAP / LLVM)

Debug Greengold programs step-by-step with breakpoints, variable inspection, and call stacks:
- Compiles with `gg build -g` so a debugger stops on `.gg` lines (DWARF; `.pdb` on Windows).
- Automatically pairs with **CodeLLDB** (`vadimcn.vscode-lldb`) or **C/C++ Tools** (`ms-vscode.cpptools` / `cppvsdbg`).
- Press `F5` or click `Debug` in the editor title bar / CodeLens to start debugging.

---

### 5. ⚙️ Build Tasks & Problem Matcher

- **VS Code Tasks (`Ctrl+Shift+B`):**
  - `gg build` (Default build task)
  - `gg build --release` (Optimized build; bounds checks stay on)
  - `gg check` (Diagnostics, no codegen)
  - `gg test` (Run all tests)
  - `gg fix` (Apply verified safe fixes)
  - `gg fmt` (Four-space layout)
- **Custom Problem Matcher:**
  - `Error` and `Warning` lines of the form `--> file:line:col GGxxxx` land in the Problems panel, with the diagnostic code attached.

---

### 6. 🛠️ VS Code Integrated Commands and Buttons

Buttons are provided in the top-right editor title bar and the right-click context menu:

| Button / Command | Description |
|---|---|
| **Greengold: Run Current File** `$(play)` | Compiles and runs the active file with `gg run`. |
| **Greengold: Run Current File (Release)** `$(rocket)` | Runs the file with `gg run --release`. Bounds checks stay on. |
| **Greengold: Debug Current File** `$(debug-alt)` | `gg build -g`, then the native debugger. |
| **Greengold: Build Binary (Debug)** `$(tools)` | `gg build`. |
| **Greengold: Build Binary (Release)** `$(package)` | `gg build --release`. |
| **Greengold: Check Current File** `$(search)` | `gg check`. No codegen. |
| **Greengold: Apply Safe Fixes** `$(wrench)` | `gg fix` applies every verified `safe` fix. |
| **Greengold: Explain Diagnostic Code** `$(question)` | `gg explain GG0301`. |
| **Greengold: Format File** `$(paintcan)` | `gg fmt`: four spaces, `else` and `elif` level with `if`. |
| **Greengold: Run Tests** `$(beaker)` | `gg test`. |
| **Greengold: Create New Project** `$(new-folder)` | `gg new`. |
| **Greengold: Generate C Bindings** `$(plug)` | `gg bindgen` from a C header. |
| **Greengold: Generate C++ Bindings** `$(plug)` | `gg bindgen --cpp` writes the `.gg` file and a shim. |
| **Greengold: Generate Documentation** `$(book)` | `gg doc` from the `#` comment above each declaration. |
| **Greengold: Write API Lock** `$(lock)` | `gg api --lock`. |
| **Greengold: Check API Lock** `$(checklist)` | `gg api --check`. |
| **Greengold: List Targets** `$(list-flat)` | `gg targets`. |
| **Greengold: Emit LLVM IR** `$(circuit-board)` | `gg emit-ll`. |
| **Greengold: Emit LLVM Bitcode** `$(file-binary)` | `gg emit-bc`. |
| **Greengold: View AST** `$(symbol-structure)` | `gg ast`. |
| **Greengold: Restart Language Server** `$(sync)` | Restarts `gg lsp`. |

---

### 7. 🎨 Syntax Highlighting and Snippets

- **Modules:** `import std.math`, `import std.math as m`, `import std.math { sqrt }`, `import "types.gg"`. Calls are `math.sqrt` and `types.Player`.
- **Visibility:** a line that is only `public` or `private`. The file starts public.
- **Variables:** `x = 1` can be changed later; `fixed x = 1` never changes.
- **Declarations & Implementations:**
  - `impl Struct:` , `impl types.Player:`, and generic `impl Box[T]:`
  - `type` aliases: `type ID = u32`, `type Matrix = [4]f64`
  - `feature` declarations: `feature Printable:`
  - `struct`, `extern struct`, `packed struct`, `align(N) struct`, and `union`
  - `enum` declarations: `enum Color:`, `enum Result[T, E]:`
  - `fn`, `hot fn`, and `comptime fn`. Methods live in `impl Type:`, not `fn Type.method`
  - `static NAME: T = expr` and `allocator alloc, resize, free`
- **Standard library concurrency** (`import std.thread`):
  - `thread.Thread.spawn`, `thread.Thread.spawn_with_param`
  - `thread.Channel.new()`, `.send()`, `.recv()`, `.close()`
  - `thread.Mutex.new()`, `.lock()`, `.unlock()`
  - `thread.AtomicI64.new()`
- **Pattern Matching & Control Flow:**
  - `if let Valid(x) = opt: ... else: ...`
  - `while let Valid(x) = iter.next(): ...`
  - Statement & expression forms (`=>` inline matches)
  - `match consume x:`, `match lend x:`
  - `require cond`
- **Integer overflow:** `overflow: wrap`, `overflow: trap`, `wrapping:` blocks, and infix `wrapping_add` / `saturating_add` / `checked_add` (and `sub` / `mul`)
- **Loops:** `for i in 0..n:`, `for i in range(n):`, `step` with a literal or expression
- **Layout and ownership:** `exclusive`, `soa`, `copy`, `dyn Feature`, `send`, `Arc`, `Shared`
- **Rejected forms are marked invalid:** `//`, `else if`, `&&`, `||`, `!x`, `++`, `--`, `;`, `let x =`, `var`, `def` / `func` / `function`, `fn Type.method`, `impl Feature for Type`, and tab characters
- **FFI and pointers:** `*T`, `*mut T`, `weak extern`, `extern ... as name`, `addr`, `ptr_cast`, `asm`, `null`. `trust` is only inside `unsafe:`
- **Unit Testing:** `test name:` blocks, `require`, and `fn test_*():`

---

## ⚙️ Configuration Settings

You can customize the following options via VS Code settings (`Ctrl+,` -> `greengold`):

```json
{
  // Enable or disable Greengold Language Server support
  "greengold.languageServer.enable": true,

  // Path to the `gg` executable. Blank: `gg` from PATH, then the installer's folder
  "greengold.path": "",

  // Only used when `gg` is not found: runs `python -m greengold` (pip or source install)
  "greengold.pythonPath": "python",

  // Debugger backend to use ("auto", "lldb", "cppvsdbg", "cppdbg")
  "greengold.debug.debugger": "auto",

  // Enable CodeLens annotations above main and test functions
  "greengold.codeLens.enable": true,

  // Enable native VS Code Test Explorer integration
  "greengold.testing.enable": true,

  // Optional custom LSP server startup command (`gg lsp` when empty)
  "greengold.languageServer.command": "",

  // .gg files use four spaces. A tab is a syntax error.
  "[gg]": {
    "editor.insertSpaces": true,
    "editor.tabSize": 4,
    "editor.detectIndentation": false
  }
}
```

---

## 📦 Installation

### 1. Install the compiler

The extension runs the `gg` command. Install it without Python from the
[latest release](https://github.com/Greengold-Lang/greengold-lang#install) (it also adds `gg` to `PATH`; restart VS Code afterwards).
If `gg` is somewhere else, set `greengold.path`.

### 2. Install the extension

Download `greengold-vscode.vsix` from the [latest release](https://github.com/Greengold-Lang/greengold-lang/releases/latest), then:

```bash
code --install-extension greengold-vscode.vsix
```

or use **Extensions → … → Install from VSIX**.

### Building the VSIX yourself

```bash
cd vscode-extension
npm ci
npx @vscode/vsce package
```

---

## 📄 License

This VS Code extension is licensed under the [MIT License](LICENSE.md).
