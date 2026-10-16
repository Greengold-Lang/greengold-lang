# Greengold for Zed

Official [Zed](https://zed.dev) editor extension for the **Greengold** (`.gg`) programming language.

Provides syntax highlighting, code outline, auto-closing brackets, official themes, file icons, code snippets, and seamless integration with the `gg lsp` language server.

---

## Features

| Feature | Description |
|---|---|
| **Tree-sitter Syntax Highlighting** | Robust parsing using [`tree-sitter-gg`](https://github.com/Greengold-Lang/tree-sitter-gg) for keywords, types, functions, strings, numbers, operators, and comments |
| **Code Outline & Symbol Navigation** | Fast symbol navigation for functions, classes, structs, traits, and test blocks in Zed's outline view |
| **Language Server (LSP)** | Automatic detection and execution of `gg lsp` (supporting completions, hover docs, go-to-definition, find references, rename, formatting, diagnostics, and inlay hints) |
| **Official Themes** | Built-in **Greengold Dark** and **Greengold Light** editor themes with tuned contrast and dedicated inlay hint styling |
| **Custom File Icons** | Custom Greengold SVG logo for `.gg` files in the file tree and tab bar |
| **Code Snippets** | Comprehensive snippets for functions, classes, structs, loops, match expressions, tests, and standard library idioms |
| **Editor Tasks** | Ready-to-use task definitions (`tasks.example.json`) for `gg run`, `gg build`, `gg check`, `gg fix`, `gg test`, `gg fmt`, and `gg doc` |

---

## Installation

### 1. From the Zed Extension Registry (Recommended)

1. Open Zed.
2. Open the command palette (`Ctrl+Shift+P` on Windows/Linux, `Cmd+Shift+P` on macOS).
3. Type `zed: extensions` and press `Enter`.
4. Search for **Greengold** and click **Install**.

### 2. Manual / Development Installation

If you are developing or testing the extension locally:

1. Clone or copy this repository to your local machine:
   ```bash
   git clone https://github.com/Greengold-Lang/zed-greengold.git
   ```
2. Open Zed.
3. Open the command palette (`Ctrl+Shift+P` / `Cmd+Shift+P`).
4. Select `zed: install dev extension`.
5. Browse to and select the `zed-greengold` folder.

---

## Configuration & Settings

Add the following to your Zed user settings (`settings.json` via `zed: open settings`):

```json
{
  "languages": {
    "Greengold": {
      "tab_size": 4,
      "hard_tabs": false,
      "format_on_save": "on"
    }
  },
  "lsp": {
    "greengold-lsp": {
      "binary": {
        // Optional: specify path if `gg` is not on your system PATH
        // "path": "C:/Users/username/AppData/Local/Greengold/bin/gg.exe",
        "arguments": ["lsp"]
      },
      "initialization_options": {}
    }
  },
  "inlay_hints": {
    "enabled": true,
    "show_type_hints": true,
    "show_parameter_hints": true
  }
}
```

### Enabling the Themes & File Icons

- **Themes:** Open the command palette, run `theme selector: toggle`, and choose **Greengold Dark** or **Greengold Light**.
- **Icons:** Run `theme selector: toggle icon theme`, and select **Greengold**.

---

## Editor Tasks

Zed allows defining workspace or global tasks triggered with `task: spawn` (`Ctrl+Alt+Space` or `Cmd+Alt+Space`).

Copy the definitions from [`tasks.example.json`](tasks.example.json) into your `.zed/tasks.json` (workspace) or `~/.config/zed/tasks.json` (global):

| Task Label | Command | Description |
|---|---|---|
| `gg run` | `gg run $ZED_FILE` | Run the active `.gg` file |
| `gg run --release` | `gg run --release $ZED_FILE` | Run with optimizations |
| `gg build` | `gg build $ZED_FILE` | Compile binary |
| `gg check` | `gg check $ZED_FILE` | Fast type and syntax check |
| `gg fix` | `gg fix $ZED_FILE` | Apply automatic linter fixes |
| `gg fmt` | `gg fmt` | Format project files |
| `gg test` | `gg test` | Run project test suite |
| `gg test (current file)` | `gg test $ZED_FILE` | Run tests in current file |
| `gg doc` | `gg doc $ZED_FILE` | Generate documentation |

---

## Grammar Development (`tree-sitter-gg`)

The Tree-sitter grammar is maintained in its dedicated repository:
👉 [https://github.com/Greengold-Lang/tree-sitter-gg](https://github.com/Greengold-Lang/tree-sitter-gg)

To regenerate the grammar from `grammar.js`:

```bash
git clone https://github.com/Greengold-Lang/tree-sitter-gg.git
cd tree-sitter-gg
npm install
npx tree-sitter generate
```

After pushing new grammar changes to GitHub, update the pinned commit SHA (`rev`) in `extension.toml`.

---

## Contributing & Publishing

To publish or update this extension in the official Zed Extensions Registry:

1. Fork the official [zed-industries/extensions](https://github.com/zed-industries/extensions) repository to your personal GitHub account.
2. Add this repository as a submodule:
   ```bash
   git submodule add https://github.com/Greengold-Lang/zed-greengold.git extensions/greengold
   ```
3. Register the extension in top-level `extensions.toml`:
   ```toml
   [greengold]
   submodule = "extensions/greengold"
   version = "0.1.0"
   ```
4. Commit and submit a Pull Request to `zed-industries/extensions`.

---

## License

This project is licensed under the [MIT License](LICENSE).
