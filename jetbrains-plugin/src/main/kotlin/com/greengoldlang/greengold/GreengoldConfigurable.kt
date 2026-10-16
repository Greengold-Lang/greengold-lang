package com.greengoldlang.greengold

import com.intellij.openapi.options.BoundConfigurable
import com.intellij.openapi.ui.DialogPanel
import com.intellij.ui.dsl.builder.bindSelected
import com.intellij.ui.dsl.builder.bindText
import com.intellij.ui.dsl.builder.columns
import com.intellij.ui.dsl.builder.COLUMNS_LARGE
import com.intellij.ui.dsl.builder.panel

/** Settings | Languages & Frameworks | Greengold */
class GreengoldConfigurable : BoundConfigurable("Greengold") {

    override fun createPanel(): DialogPanel {
        val state = GreengoldSettings.getInstance().state
        return panel {
            row("Path to gg:") {
                textField()
                    .columns(COLUMNS_LARGE)
                    .bindText(state::path)
                    .comment("Leave blank to use `gg` from PATH (or the folder the installers use).")
            }
            row("Python path:") {
                textField()
                    .columns(COLUMNS_LARGE)
                    .bindText(state::pythonPath)
                    .comment("Only used when `gg` is not found: runs `python -m greengold`.")
            }
            group("Language Server") {
                row {
                    checkBox("Enable Greengold Language Server (LSP)").bindSelected(state::lspEnabled)
                }
                row("Custom command:") {
                    textField()
                        .columns(COLUMNS_LARGE)
                        .bindText(state::lspCommand)
                        .comment("Defaults to `gg lsp` if left blank. Restart the IDE after changing it.")
                }
            }
        }
    }
}
