package com.greengoldlang.greengold

import org.jetbrains.plugins.textmate.api.TextMateBundleProvider
import java.nio.file.Files
import java.nio.file.Path
import java.nio.file.StandardCopyOption

/**
 * Registers the Greengold TextMate bundle (the same grammar, language configuration and snippets
 * the VS Code extension ships) so highlighting, comment toggling, brackets and snippets work.
 */
class GreengoldTextMateBundleProvider : TextMateBundleProvider {

    private val files = listOf(
        "package.json",
        "language-configuration.json",
        "syntaxes/gg.tmLanguage.json",
        "snippets/snippets.json",
        "icons/greengold.png",
    )

    override fun getBundles(): List<TextMateBundleProvider.PluginBundle> {
        val target: Path = Files.createTempDirectory("greengold-textmate")
        for (name in files) {
            val stream = javaClass.classLoader.getResourceAsStream("textmate/greengold/$name") ?: continue
            val out = target.resolve(name)
            Files.createDirectories(out.parent)
            stream.use { Files.copy(it, out, StandardCopyOption.REPLACE_EXISTING) }
        }
        return listOf(TextMateBundleProvider.PluginBundle("Greengold", target))
    }
}
