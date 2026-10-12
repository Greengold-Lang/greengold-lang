# Package the VS Code extension and publish it from this machine.
#   $env:OVSX_PAT  token from open-vsx.org (Open VSX: VSCodium, Cursor, Gitpod ...)
#   $env:VSCE_PAT  Azure DevOps token (VS Code Marketplace)
# A registry whose token is not set is skipped. The version comes from vscode-extension/package.json.
# Bump it first: cd vscode-extension; npm version patch --no-git-tag-version
$ErrorActionPreference = "Stop"
Push-Location (Join-Path $PSScriptRoot "..\vscode-extension")
try {
    $failed = @()
    npm ci --omit=dev
    if ($LASTEXITCODE -ne 0) { throw "npm ci failed" }

    $vsix = "greengold-vscode.vsix"
    npx --yes @vscode/vsce package --out $vsix
    if ($LASTEXITCODE -ne 0) { throw "vsce package failed" }

    if ($env:OVSX_PAT) {
        npx --yes ovsx publish $vsix -p $env:OVSX_PAT
        if ($LASTEXITCODE -ne 0) { $failed += "Open VSX" }
    } else { Write-Host "OVSX_PAT not set: skipping Open VSX" }

    if ($env:VSCE_PAT) {
        npx --yes @vscode/vsce publish --packagePath $vsix -p $env:VSCE_PAT
        if ($LASTEXITCODE -ne 0) { $failed += "the VS Code Marketplace" }
    } else { Write-Host "VSCE_PAT not set: skipping the VS Code Marketplace" }
    # A registry is tried even when the other one failed (for example "version already published").
    if ($failed.Count -gt 0) { throw "Publishing failed for: $($failed -join ', ')" }
} finally {
    Pop-Location
}
