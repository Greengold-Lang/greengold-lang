# Greengold for Zed

Zed port of the VS Code extension.

| Feature | How |
|---|---|
| Syntax highlighting, brackets, outline | `languages/greengold/*` and the grammar in [`../tree-sitter-gg`](../tree-sitter-gg) |
| Language server (`gg lsp`) | `src/lib.rs` (setting, then `gg` on PATH, then `python -m greengold`) |
| Snippets | `snippets/greengold.json` |
| Themes (Dark & Light) | `themes/greengold.json` (`theme selector: toggle`) |
| File Icon Theme | `icon_themes/greengold.json` (`theme selector: toggle icon theme`) |
| Run / build / check / fix / fmt / test / doc / ... | `tasks.example.json` (copy into `~/.config/zed/tasks.json` or `.zed/tasks.json`, run via `task: spawn`) |

Zed has no API for extensions to add commands, CodeLens, a Test Explorer or debugger launchers, so those VS Code
features are covered by tasks and the language server only.

The grammar is lexical: it does not model Greengold's indentation blocks, so Zed's smart auto-indent after `:`
is not available.

## Install as a dev extension

1. Commit `tree-sitter-gg` (it contains the generated `src/parser.c`) and copy the commit SHA.
2. In [`extension.toml`](extension.toml) set `rev` to that SHA. For an unpushed local checkout change `repository`
   to `file:///C:/greengold` (the folder that holds the git repo; `path = "tree-sitter-gg"` stays).
3. Zed: command palette → `zed: install dev extension` → pick this `zed-extension` folder.
   Rust must be installed through rustup (the extension compiles to WASM).

## Settings

```json
{
  "lsp": {
    "greengold-lsp": {
      "binary": { "path": "C:/Users/you/AppData/Local/Greengold/bin/gg.exe", "arguments": ["lsp"] }
    }
  },
  "languages": {
    "Greengold": { "tab_size": 4, "format_on_save": "off" }
  }
}
```

## Regenerating the grammar

```sh
cd ../tree-sitter-gg
npm install
npx tree-sitter generate
```
