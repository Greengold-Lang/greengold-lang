use zed_extension_api::{self as zed, settings::LspSettings, LanguageServerId, Result};

struct GreengoldExtension;

impl GreengoldExtension {
    /// Resolution order mirrors the VS Code extension: user setting, `gg` on PATH,
    /// then `python -m greengold` (pip or source install).
    fn server_command(
        &self,
        language_server_id: &LanguageServerId,
        worktree: &zed::Worktree,
    ) -> Result<zed::Command> {
        let binary = LspSettings::for_worktree(language_server_id.as_ref(), worktree)
            .ok()
            .and_then(|settings| settings.binary);

        let env = worktree.shell_env();

        if let Some(binary) = binary {
            if let Some(path) = binary.path {
                return Ok(zed::Command {
                    command: path,
                    args: binary.arguments.unwrap_or_else(|| vec!["lsp".to_string()]),
                    env,
                });
            }
        }

        if let Some(path) = worktree.which("gg") {
            return Ok(zed::Command {
                command: path,
                args: vec!["lsp".to_string()],
                env,
            });
        }

        for python in ["python", "python3"] {
            if let Some(path) = worktree.which(python) {
                return Ok(zed::Command {
                    command: path,
                    args: vec!["-m".to_string(), "greengold".to_string(), "lsp".to_string()],
                    env,
                });
            }
        }

        Err("could not find `gg`. Install Greengold, or set lsp.greengold-lsp.binary.path in Zed settings."
            .to_string())
    }
}

impl zed::Extension for GreengoldExtension {
    fn new() -> Self {
        Self
    }

    fn language_server_command(
        &mut self,
        language_server_id: &LanguageServerId,
        worktree: &zed::Worktree,
    ) -> Result<zed::Command> {
        self.server_command(language_server_id, worktree)
    }

    fn language_server_initialization_options(
        &mut self,
        language_server_id: &LanguageServerId,
        worktree: &zed::Worktree,
    ) -> Result<Option<zed::serde_json::Value>> {
        let settings = LspSettings::for_worktree(language_server_id.as_ref(), worktree)
            .ok()
            .and_then(|settings| settings.initialization_options.clone());
        Ok(settings)
    }
}

zed::register_extension!(GreengoldExtension);
