# Greengold installer for Windows (PowerShell 5.1+). No Python needed.
#   irm https://raw.githubusercontent.com/Greengold-Lang/greengold-lang/main/installer/install.ps1 | iex
# Options (environment): GG_VERSION=0.3.3 (default: latest), GG_INSTALL_DIR, GG_NO_MODIFY_PATH=1
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12

$repo = if ($env:GG_REPO) { $env:GG_REPO } else { 'Greengold-Lang/greengold-lang' }
$installDir = if ($env:GG_INSTALL_DIR) { $env:GG_INSTALL_DIR } else { Join-Path $env:LOCALAPPDATA 'Greengold\bin' }

$arch = if ($env:PROCESSOR_ARCHITEW6432) { $env:PROCESSOR_ARCHITEW6432 } else { $env:PROCESSOR_ARCHITECTURE }
if ($arch -ne 'AMD64') { throw "Unsupported CPU $arch (only 64-bit x86 Windows builds exist)." }
$asset = 'gg-windows-x64.exe'

if ($env:GG_VERSION) { $base = "https://github.com/$repo/releases/download/v$($env:GG_VERSION.TrimStart('v'))" }
else { $base = "https://github.com/$repo/releases/latest/download" }

$tmp = Join-Path ([IO.Path]::GetTempPath()) ('gg-install-' + [Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $tmp | Out-Null
try {
    Write-Host "Downloading $asset ..."
    Invoke-WebRequest -UseBasicParsing "$base/$asset" -OutFile (Join-Path $tmp $asset)

    $sumsFile = Join-Path $tmp 'SHA256SUMS.txt'
    $haveSums = $true
    try { Invoke-WebRequest -UseBasicParsing "$base/SHA256SUMS.txt" -OutFile $sumsFile } catch { $haveSums = $false }
    if ($haveSums) {
        $want = $null
        foreach ($l in Get-Content $sumsFile) {
            $f = $l -split '\s+'
            if ($f.Count -ge 2 -and $f[1].TrimStart('*') -eq $asset) { $want = $f[0].ToLower(); break }
        }
        $got = (Get-FileHash (Join-Path $tmp $asset) -Algorithm SHA256).Hash.ToLower()
        if (-not $want -or $want -ne $got) { throw 'Checksum mismatch; nothing was installed.' }
    } else {
        Write-Warning 'No SHA256SUMS.txt for this release; skipping verification.'
    }

    New-Item -ItemType Directory -Force -Path $installDir | Out-Null
    $dest = Join-Path $installDir 'gg.exe'
    if (Test-Path $dest) {   # a running gg.exe cannot be overwritten, but it can be renamed
        $old = "$dest.old"
        if (Test-Path $old) { Remove-Item $old -Force -ErrorAction SilentlyContinue }
        Move-Item $dest $old -Force
    }
    Move-Item (Join-Path $tmp $asset) $dest -Force
    $ver = & $dest --version | Select-Object -First 1
    Write-Host "Installed $ver to $dest"
} finally {
    Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue
}

if (-not $env:GG_NO_MODIFY_PATH) {
    $userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
    $parts = @($userPath -split ';' | Where-Object { $_ })
    if ($parts -notcontains $installDir) {
        $newPath = (@($parts) + $installDir) -join ';'
        [Environment]::SetEnvironmentVariable('Path', $newPath, 'User')
        Write-Host "Added $installDir to your user PATH."
    }
    if (($env:Path -split ';') -notcontains $installDir) { $env:Path = "$env:Path;$installDir" }
}
Write-Host 'Open a new terminal and try:  gg --version'
Write-Host 'Update later with:  gg update'
