package com.greengoldlang.greengold

import com.intellij.openapi.application.ApplicationManager
import com.intellij.openapi.components.PersistentStateComponent
import com.intellij.openapi.components.State
import com.intellij.openapi.components.Storage

/** Application-level settings; the counterpart of the `greengold.*` VS Code settings. */
@State(name = "GreengoldSettings", storages = [Storage("greengold.xml")])
class GreengoldSettings : PersistentStateComponent<GreengoldSettings.Data> {

    class Data {
        /** Path to the `gg` executable. Blank: `gg` from PATH, then the installer folder, then python. */
        var path: String = ""

        /** Only used when `gg` is not found: runs `python -m greengold`. */
        var pythonPath: String = "python"

        var lspEnabled: Boolean = true

        /** Custom command for the language server (defaults to `gg lsp`). */
        var lspCommand: String = ""
    }

    private var data = Data()

    override fun getState(): Data = data

    override fun loadState(state: Data) {
        data = state
    }

    companion object {
        fun getInstance(): GreengoldSettings =
            ApplicationManager.getApplication().getService(GreengoldSettings::class.java)
    }
}
