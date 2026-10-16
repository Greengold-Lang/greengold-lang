# Greengold for JetBrains IDEs

Plugin for IntelliJ IDEA, PyCharm, CLion, GoLand, RustRover, WebStorm and the other JetBrains IDEs (2025.1+).

| Feature | How |
|---|---|
| Syntax highlighting, brackets, comments, snippets | bundled TextMate bundle (same grammar, language configuration and snippets as the VS Code extension) |
| Themes (Greengold Dark & Light) | bundled UI themes & editor color schemes (Settings → Appearance & Behavior → Appearance → Theme) |
| File Icon | platform `fileIconProvider` for `.gg` files |
| Language server (`gg lsp`): diagnostics, hover, completion, definition, references, rename, formatting | platform LSP API (optional dependency `com.intellij.modules.lsp`) |
| Run / build / check / fix / fmt / test / doc / emit / ast / api / targets / explain / new / bindgen | **Tools → Greengold** and the editor context menu |
| Clickable `--> file:line:col` locations in compiler output | console filter |
| `gg` discovery: setting → `PATH` → installer folder → `python -m greengold` | Settings → Languages & Frameworks → Greengold |

Not ported: gutter run icons / CodeLens, the Test Explorer tree and the debugger launcher. TextMate files have no
PSI to attach run markers to; use the actions (default shortcut for **Run File**: `Ctrl+Alt+Shift+G`).

## Build

Requires JDK 21.

```sh
cd jetbrains-plugin
gradle wrapper        # once, needs Gradle installed (or copy a wrapper from another project)
./gradlew buildPlugin # -> build/distributions/*.zip
./gradlew runIde      # sandbox IDE
```

Install the ZIP via Settings → Plugins → ⚙ → Install Plugin from Disk.
