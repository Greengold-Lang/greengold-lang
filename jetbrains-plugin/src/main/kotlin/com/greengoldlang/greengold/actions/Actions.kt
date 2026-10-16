package com.greengoldlang.greengold.actions

import com.greengoldlang.greengold.GgRunner
import com.intellij.notification.NotificationType
import com.intellij.openapi.actionSystem.ActionUpdateThread
import com.intellij.openapi.actionSystem.AnAction
import com.intellij.openapi.actionSystem.AnActionEvent
import com.intellij.openapi.actionSystem.CommonDataKeys
import com.intellij.openapi.fileChooser.FileChooser
import com.intellij.openapi.fileChooser.FileChooserDescriptorFactory
import com.intellij.openapi.fileEditor.FileDocumentManager
import com.intellij.openapi.project.DumbAware
import com.intellij.openapi.project.Project
import com.intellij.openapi.ui.Messages
import com.intellij.openapi.vfs.VfsUtil
import com.intellij.openapi.vfs.VirtualFile
import java.io.File

private fun AnActionEvent.ggFile(): VirtualFile? {
    val file = getData(CommonDataKeys.VIRTUAL_FILE) ?: getData(CommonDataKeys.EDITOR)?.let {
        FileDocumentManager.getInstance().getFile(it.document)
    }
    return file?.takeIf { it.extension == "gg" }
}

/** Base class: runs on the background thread for `update`, needs an open project. */
abstract class GgAction : AnAction(), DumbAware {
    override fun getActionUpdateThread(): ActionUpdateThread = ActionUpdateThread.BGT
    override fun update(e: AnActionEvent) {
        e.presentation.isEnabled = e.project != null
    }
}

/** `gg <command> [extra] --color never <current .gg file>` */
abstract class FileCommandAction(
    private val command: String,
    private val extra: List<String> = emptyList(),
    private val refreshAfter: Boolean = false,
) : GgAction() {
    override fun update(e: AnActionEvent) {
        e.presentation.isEnabled = e.project != null && e.ggFile() != null
    }

    override fun actionPerformed(e: AnActionEvent) {
        val project = e.project ?: return
        val file = e.ggFile() ?: return GgRunner.notify(
            project, "Only .gg files can be run or built.", NotificationType.WARNING
        )
        FileDocumentManager.getInstance().saveAllDocuments()
        val args = listOf(command) + extra + listOf("--color", "never", file.path)
        val title = (listOf("gg", command) + extra).joinToString(" ") + " " + file.name
        GgRunner.run(project, title, args, file.parent?.path ?: project.basePath) {
            if (refreshAfter) VfsUtil.markDirtyAndRefresh(true, false, false, file)
        }
    }
}

/** `gg <args...>` in the project directory. */
abstract class PlainCommandAction(private val args: List<String>) : GgAction() {
    override fun actionPerformed(e: AnActionEvent) {
        val project = e.project ?: return
        FileDocumentManager.getInstance().saveAllDocuments()
        GgRunner.run(project, (listOf("gg") + args).joinToString(" "), args)
    }
}

class RunAction : FileCommandAction("run")
class RunReleaseAction : FileCommandAction("run", listOf("--release"))
class BuildAction : FileCommandAction("build")
class BuildReleaseAction : FileCommandAction("build", listOf("--release"))
class CheckAction : FileCommandAction("check")
class FixAction : FileCommandAction("fix", refreshAfter = true)
class FormatAction : FileCommandAction("fmt", refreshAfter = true)
class TestFileAction : FileCommandAction("test")
class DocAction : FileCommandAction("doc")
class EmitLlvmAction : FileCommandAction("emit-ll")
class EmitBitcodeAction : FileCommandAction("emit-bc")
class AstAction : FileCommandAction("ast")

class TestAction : PlainCommandAction(listOf("test", "--color", "never"))
class ApiLockAction : PlainCommandAction(listOf("api", "--lock"))
class ApiCheckAction : PlainCommandAction(listOf("api", "--check"))
class TargetsAction : PlainCommandAction(listOf("targets"))

class ExplainAction : GgAction() {
    override fun actionPerformed(e: AnActionEvent) {
        val project = e.project ?: return
        val code = Messages.showInputDialog(
            project,
            "Diagnostic code, e.g. GG0301",
            "Greengold: Explain Diagnostic",
            null,
            "GG0301",
            object : com.intellij.openapi.ui.InputValidator {
                override fun checkInput(inputString: String?) =
                    Regex("^GG\\d{4}$", RegexOption.IGNORE_CASE).matches(inputString?.trim().orEmpty())

                override fun canClose(inputString: String?) = checkInput(inputString)
            },
        ) ?: return
        GgRunner.run(project, "gg explain ${code.trim()}", listOf("explain", code.trim()))
    }
}

class NewProjectAction : GgAction() {
    override fun actionPerformed(e: AnActionEvent) {
        val project = e.project ?: return
        val name = Messages.showInputDialog(
            project, "Enter the new Greengold package name", "Greengold: New Project", null, "my_project", null
        )?.trim()?.takeIf { it.isNotEmpty() } ?: return
        FileChooser.chooseFile(
            FileChooserDescriptorFactory.createSingleFolderDescriptor().withTitle("Select Parent Directory"),
            project,
            null,
        ) { parent ->
            val dir = File(parent.path, name).path
            GgRunner.run(project, "gg new $name", listOf("new", name, "--path", dir), parent.path) {
                VfsUtil.markDirtyAndRefresh(true, true, true, parent)
                GgRunner.notify(project, "Greengold package '$name' created in $dir")
            }
        }
    }
}

abstract class AbstractBindgenAction(private val cpp: Boolean) : GgAction() {
    override fun actionPerformed(e: AnActionEvent) {
        val project = e.project ?: return
        val extensions = if (cpp) arrayOf("h", "hpp", "hh", "hxx") else arrayOf("h")
        val descriptor = FileChooserDescriptorFactory.createSingleFileDescriptor()
            .withTitle(if (cpp) "Select C++ Header" else "Select C Header")
            .withExtensionFilter(if (cpp) "C++ Header Files" else "C Header Files", *extensions)
        FileChooser.chooseFile(descriptor, project, null) { header ->
            val out = header.path.replace(Regex("\\.(hpp|hh|hxx|h)$", RegexOption.IGNORE_CASE), ".gg")
            val args = mutableListOf("bindgen")
            if (cpp) args += "--cpp"
            args += listOf(header.path, "-o", out)
            GgRunner.run(project, "gg bindgen ${header.name}", args, header.parent?.path) {
                VfsUtil.markDirtyAndRefresh(false, false, true, header.parent)
                GgRunner.notify(project, "Greengold bindings generated at ${File(out).name}")
            }
        }
    }
}

class BindgenAction : AbstractBindgenAction(false)
class BindgenCppAction : AbstractBindgenAction(true)
