package com.greengoldlang.greengold.lsp

import com.greengoldlang.greengold.GgRunner
import com.greengoldlang.greengold.GreengoldSettings
import com.intellij.execution.configurations.GeneralCommandLine
import com.intellij.openapi.project.Project
import com.intellij.openapi.vfs.VirtualFile
import com.intellij.platform.lsp.api.LspServerSupportProvider
import com.intellij.platform.lsp.api.ProjectWideLspServerDescriptor

class GreengoldLspServerSupportProvider : LspServerSupportProvider {
    override fun fileOpened(
        project: Project,
        file: VirtualFile,
        serverStarter: LspServerSupportProvider.LspServerStarter,
    ) {
        if (file.extension == "gg" && GreengoldSettings.getInstance().state.lspEnabled) {
            serverStarter.ensureServerStarted(GreengoldLspServerDescriptor(project))
        }
    }
}

private class GreengoldLspServerDescriptor(project: Project) :
    ProjectWideLspServerDescriptor(project, "Greengold") {

    override fun isSupportedFile(file: VirtualFile): Boolean = file.extension == "gg"

    override fun createCommandLine(): GeneralCommandLine {
        val custom = GreengoldSettings.getInstance().state.lspCommand.trim()
        if (custom.isNotEmpty()) {
            return GeneralCommandLine(custom.split(Regex("\\s+"))).withWorkDirectory(project.basePath)
        }
        return GgRunner.commandLine(listOf("lsp"), project.basePath)
    }
}
