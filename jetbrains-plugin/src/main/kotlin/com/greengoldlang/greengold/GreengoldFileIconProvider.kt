package com.greengoldlang.greengold

import com.intellij.ide.FileIconProvider
import com.intellij.openapi.project.Project
import com.intellij.openapi.util.IconLoader
import com.intellij.openapi.vfs.VirtualFile
import javax.swing.Icon

class GreengoldFileIconProvider : FileIconProvider {
    companion object {
        @JvmField
        val ICON: Icon = IconLoader.getIcon("/icons/greengold.png", GreengoldFileIconProvider::class.java)
    }

    override fun getIcon(file: VirtualFile, flags: Int, project: Project?): Icon? {
        if (file.extension.equals("gg", ignoreCase = true)) {
            return ICON
        }
        return null
    }
}
