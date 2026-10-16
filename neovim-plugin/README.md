# greengold.nvim

Full IDE experience for the **Greengold** (`.gg`) programming language in Neovim. Port of the official VS Code extension.

Requires Neovim 0.10+ and the `gg` compiler.

## Features

| Feature | Details |
|---|---|
| **Filetype & Syntax** | Automatic `.gg` detection, `#` comments, 4-space indentation, full syntax highlighting |
| **Language Server (LSP)** | Built-in `vim.lsp` client for `gg lsp`: diagnostics, completion, hover, go-to-definition, references, rename, formatting, inlay hints |
| **Themes** | Official **Greengold Dark** & **Greengold Light** colorschemes (`:colorscheme greengold`, `greengold-dark`, `greengold-light`) |
| **File Icons** | Native integration with `nvim-web-devicons` & `mini.icons` for `.gg` files |
| **Interactive Commands** | `:GgRun`, `:GgBuild`, `:GgCheck`, `:GgFix`, `:GgFormat`, `:GgTest`, `:GgDoc`, `:GgNew`, `:GgBindgen`, `:GgMenu` |
| **Test Discovery** | Discovers `test_*` functions and `test:` blocks; reports results as inline diagnostics (`:GgTestNearest`, `:GgTest`) |
| **CodeLens / Virtual Text** | Visual `▶` signs and runners above `fn main` and test blocks |
| **Snippets** | VS Code formatted snippets (`snippets/gg.json`) compatible with LuaSnip, nvim-snippets, and blink.cmp |
| **Native Debugging** | Integrated with [nvim-dap](https://github.com/mfussenegger/nvim-dap) via `:GgDebug` (CodeLLDB, lldb-dap, or gdb) |

---

## Installation

### [lazy.nvim](https://github.com/folke/lazy.nvim)

```lua
{
  "Greengold-Lang/greengold.nvim",
  ft = "gg",
  opts = {
    -- configuration options (see below)
  },
}
```

### [packer.nvim](https://github.com/wbthomason/packer.nvim)

```lua
use {
  "Greengold-Lang/greengold.nvim",
  ft = { "gg" },
  config = function()
    require("greengold").setup({})
  end
}
```

### [vim-plug](https://github.com/junegunn/vim-plug)

```vim
Plug 'Greengold-Lang/greengold.nvim'
```

---

## Configuration (Defaults)

```lua
require("greengold").setup({
  -- Path to the `gg` executable.
  -- Leave blank to auto-detect: checks PATH, default installer directories, or `python -m greengold`.
  path = "",

  -- Fallback python command if standalone `gg` binary is not found.
  python_path = "python",

  -- Language Server Protocol (gg lsp)
  language_server = {
    enable = true,
    command = "", -- custom start command (defaults to `gg lsp`)
  },

  -- Extra options merged into vim.lsp client config (on_attach, capabilities, etc.)
  lsp = {},

  -- Native debugging configuration via nvim-dap
  debug = {
    debugger = "auto", -- "auto" | "codelldb" | "lldb" | "cppdbg"
  },

  -- CodeLens indicators above `fn main()` and test definitions
  codelens = {
    enable = true,
  },

  -- Built-in test runner
  testing = {
    enable = true,
  },

  format_on_save = false,
  fix_on_save = false, -- applies source.fixAll.greengold on save
  keymaps = true,      -- registers buffer-local <leader>g* shortcuts in .gg files
})
```

---

## Colorscheme

`greengold.nvim` ships with both Dark and Light variants ported directly from the official VS Code themes:

```vim
" Dark theme (default)
:colorscheme greengold
:colorscheme greengold-dark

" Light theme
:colorscheme greengold-light
```

In Lua:
```lua
vim.cmd("colorscheme greengold")
```

---

## Keymaps

When `keymaps = true`, the following buffer-local shortcuts are available in `.gg` buffers:

| Keymap | Command | Description |
|---|---|---|
| `<leader>gr` | `:GgRun` | Run current file (`gg run`) |
| `<leader>gR` | `:GgRunRelease` | Run current file in release mode (`gg run --release`) |
| `<leader>gd` | `:GgDebug` | Debug current file with `nvim-dap` |
| `<leader>gb` | `:GgBuild` | Build binary (`gg build`) |
| `<leader>gc` | `:GgCheck` | Check syntax and diagnostics (`gg check`) |
| `<leader>gt` | `:GgTest` | Run all tests in file |
| `<leader>gn` | `:GgTestNearest` | Run test under cursor |
| `<leader>gf` | `:GgFormat` | Format file (`gg fmt` / LSP) |
| `<leader>gm` | `:GgMenu` | Open Greengold actions menu |

---

## Snippets with LuaSnip

If you are using [LuaSnip](https://github.com/L3MON4D3/LuaSnip), load the snippets using the VS Code loader:

```lua
require("luasnip.loaders.from_vscode").lazy_load()
```

---

## Troubleshooting

- Run `:checkhealth lsp` to ensure your Neovim LSP client is active.
- Run `:GgMenu` to access all compiler actions interactively.
- If `gg` is not detected, set `path` explicitly in your `setup()` or add the Greengold binary folder to your system `PATH`.
