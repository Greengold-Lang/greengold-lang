plugins {
    id("java")
    id("org.jetbrains.kotlin.jvm") version "2.1.20"
    id("org.jetbrains.intellij.platform") version "2.10.2"
}

group = "com.greengoldlang"
version = "0.1.0"

repositories {
    mavenCentral()
    intellijPlatform {
        defaultRepositories()
    }
}

dependencies {
    intellijPlatform {
        // Compiles against IntelliJ IDEA Ultimate (it contains the LSP API); the plugin runs in every JetBrains IDE (IDEA, PyCharm,
        // CLion, GoLand, RustRover, WebStorm, ...) because it only needs the platform and TextMate.
        intellijIdeaUltimate("2025.1")
        bundledPlugin("org.jetbrains.plugins.textmate")
        pluginVerifier()
        zipSigner()
    }
}

kotlin {
    jvmToolchain(21)
}

intellijPlatform {
    pluginConfiguration {
        name = "Greengold Language Support"
        ideaVersion {
            sinceBuild = "251"
            untilBuild = provider { null }
        }
    }
    publishing {
        token = providers.environmentVariable("PUBLISH_TOKEN")
    }
}

tasks {
    wrapper {
        gradleVersion = "8.13"
    }
}
