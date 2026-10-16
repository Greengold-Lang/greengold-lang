# Greengold for Neovim

Neovim port of the VS Code extension. Needs Neovim 0.10+ and the `gg` compiler.

| Feature | How |
|---|---|
| Filetype, syntax, indent, `#` comments, 4-space indent | `ftdetect/`, `syntax/`, `indent/`, `ftplugin/` |
| Language server (`gg lsp`): diagnostics, hover, completion, definition, references, rename, formatting, inlay hints | built-in `vim.lsp` (started per buffer) |
| Run / build / check / fix / fmt / test / doc / emit / ast / api / targets / explain / bindgen / new | `:Gg*` commands, `:GgMenu` |
| Test discovery (`test_*` functions, `test:` blocks) + run result as diagnostics | `:GgTestNearest`, `:GgTest` |
| "CodeLens" over `fn main` and tests | virtual text and a `▶` sign |
| Snippets | `snippets/gg.json` (VS Code format: LuaSnip, nvim-snippets, blink.cmp) |
| Colorschemes (Greengold Dark & Light) | `:colorscheme greengold` (veya `greengold-dark`, `greengold-light`) |
| Native debugging | `:GgDebug` (needs [nvim-dap](https://github.com/mfussenegger/nvim-dap) + codelldb/lldb-dap/gdb) |

## Install

lazy.nvim:

```lua
{
  "Greengold-Lang/greengold-lang",
  -- the plugin lives in a subfolder of the main repository
  config = function(plugin)
    vim.opt.rtp:append(plugin.dir .. "/neovim-plugin")
    require("greengold").setup({})
  end,
  ft = "gg",
}
```

Local checkout: `vim.opt.rtp:append("C:/greengold/neovim-plugin")` in `init.lua`.

Snippets with LuaSnip: `require("luasnip.loaders.from_vscode").lazy_load({ paths = { "<path>/neovim-plugin" } })`.

## Options (defaults)

```lua
require("greengold").setup({
  path = "",                 -- gg executable; blank = PATH, then installer folder, then python -m greengold
  python_path = "python",
  language_server = { enable = true, command = "" },  -- command defaults to `gg lsp`
  lsp = {},                  -- merged into the vim.lsp client config (on_attach, capabilities, ...)
  debug = { debugger = "auto" },   -- auto | codelldb | lldb | cppdbg
  codelens = { enable = true },
  testing = { enable = true },
  format_on_save = false,
  fix_on_save = false,       -- source.fixAll.greengold on save
  keymaps = true,            -- buffer-local <leader>g* maps
})
```

Keymaps (buffer-local): `<leader>gr` run, `gR` release, `gd` debug, `gb` build, `gc` check, `gt` tests, `gn` test at cursor, `gf` format, `gm` menu.

Run `:GgMenu` for the full action list. Use `:checkhealth lsp` if the server does not start.
