package com.greengoldlang.greengold

import com.intellij.execution.RunContentExecutor
import com.intellij.execution.configurations.GeneralCommandLine
import com.intellij.execution.filters.Filter
import com.intellij.execution.filters.OpenFileHyperlinkInfo
import com.intellij.execution.process.KillableColoredProcessHandler
import com.intellij.execution.process.ProcessEvent
import com.intellij.execution.process.ProcessListener
import com.intellij.execution.ui.ConsoleView
import com.intellij.execution.filters.TextConsoleBuilderFactory
import com.intellij.notification.NotificationGroupManager
import com.intellij.notification.NotificationType
import com.intellij.openapi.project.Project
import com.intellij.openapi.util.SystemInfo
import com.intellij.openapi.vfs.LocalFileSystem
import java.io.File
import java.nio.charset.StandardCharsets

/** Finds the compiler and runs `gg` commands in a Run tool window tab. */
object GgRunner {

    data class Invocation(val cmd: String, val pre: List<String>)

    private fun onPath(name: String): String? {
        val exts = if (SystemInfo.isWindows) listOf(".exe", ".cmd", ".bat") else listOf("")
        for (dir in (System.getenv("PATH") ?: "").split(File.pathSeparator)) {
            if (dir.isBlank()) continue
            for (ext in exts) {
                val f = File(dir, name + ext)
                if (f.isFile) return f.absolutePath
            }
        }
        return null
    }

    /** Order: the settings path, `gg` on PATH, the installer folder, then `python -m greengold`. */
    fun invocation(): Invocation {
        val s = GreengoldSettings.getInstance().state
        if (s.path.isNotBlank()) return Invocation(s.path, emptyList())
        onPath("gg")?.let { return Invocation(it, emptyList()) }
        val home = System.getProperty("user.home")
        val installed = if (SystemInfo.isWindows) {
            val base = System.getenv("LOCALAPPDATA") ?: File(home, "AppData/Local").path
            File(base, "Greengold/bin/gg.exe")
        } else {
            File(home, ".greengold/bin/gg")
        }
        if (installed.exists()) return Invocation(installed.absolutePath, emptyList())
        return Invocation(s.pythonPath.ifBlank { "python" }, listOf("-m", "greengold"))
    }

    fun commandLine(args: List<String>, workDir: String?): GeneralCommandLine {
        val gg = invocation()
        return GeneralCommandLine(listOf(gg.cmd) + gg.pre + args)
            .withCharset(StandardCharsets.UTF_8)
            .withEnvironment("PYTHONUNBUFFERED", "1")
            .withEnvironment("PYTHONIOENCODING", "utf-8")
            .apply { if (workDir != null) withWorkDirectory(workDir) }
    }

    /** Makes `--> path:line:col` locations in compiler output clickable (the `$greengold` problem matcher). */
    private class OutputFilter(private val project: Project, private val workDir: String?) : Filter {
        private val location = Regex("""^\s*-->\s+(.+?):(\d+):(\d+)""")

        override fun applyFilter(line: String, entireLength: Int): Filter.Result? {
            val m = location.find(line) ?: return null
            var path = m.groupValues[1]
            if (!File(path).isAbsolute && workDir != null) path = File(workDir, path).path
            val file = LocalFileSystem.getInstance().refreshAndFindFileByPath(path.replace('\\', '/')) ?: return null
            val lineStart = entireLength - line.length
            val start = lineStart + m.groups[1]!!.range.first
            val end = lineStart + m.groups[3]!!.range.last + 1
            val info = OpenFileHyperlinkInfo(
                project, file, m.groupValues[2].toInt() - 1, m.groupValues[3].toInt() - 1
            )
            return Filter.Result(start, end, info)
        }
    }

    fun run(
        project: Project,
        title: String,
        args: List<String>,
        workDir: String? = project.basePath,
        onSuccess: (() -> Unit)? = null,
    ) {
        val handler = try {
            KillableColoredProcessHandler(commandLine(args, workDir))
        } catch (e: Exception) {
            notify(
                project,
                "Could not start `gg`: ${e.message}. Install it, or set the path in Settings | Languages & Frameworks | Greengold.",
                NotificationType.ERROR,
            )
            return
        }
        val console: ConsoleView = TextConsoleBuilderFactory.getInstance().createBuilder(project).console
        console.addMessageFilter(OutputFilter(project, workDir))
        if (onSuccess != null) {
            handler.addProcessListener(object : ProcessListener {
                override fun processTerminated(event: ProcessEvent) {
                    if (event.exitCode == 0) onSuccess()
                }
            })
        }
        RunContentExecutor(project, handler)
            .withTitle("Greengold: $title")
            .withConsole(console)
            .withActivateToolWindow(true)
            .run()
    }

    fun notify(project: Project?, content: String, type: NotificationType = NotificationType.INFORMATION) {
        NotificationGroupManager.getInstance()
            .getNotificationGroup("Greengold")
            .createNotification(content, type)
            .notify(project)
    }
}
