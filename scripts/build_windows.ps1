[CmdletBinding()]
param(
    [string]$Python = "python",
    [string]$CargoTargetDirectory = ""
)

$projectDirectory = Split-Path -Parent $PSScriptRoot
if (-not $CargoTargetDirectory) {
    $CargoTargetDirectory = Join-Path $projectDirectory ".build\cargo"
}

$hostTriple = (& rustc --print host-tuple).Trim()
if ($LASTEXITCODE -ne 0) {
    throw "Rust MSVC toolchain is required."
}

$sidecarName = "growth-mirror-service-$hostTriple"
$sidecarDirectory = Join-Path $projectDirectory "src-tauri\binaries"
$pyInstallerWork = Join-Path $projectDirectory ".build\pyinstaller"
$specDirectory = Join-Path $projectDirectory ".build"
$entrypoint = Join-Path $projectDirectory "src\growth_mirror\sidecar.py"

New-Item -ItemType Directory -Path $sidecarDirectory -Force | Out-Null
New-Item -ItemType Directory -Path $specDirectory -Force | Out-Null

Push-Location $projectDirectory
try {
    & $Python -m pip install -e ".[api,desktop-build]"
    if ($LASTEXITCODE -ne 0) { throw "Python dependency installation failed." }

    npm install
    if ($LASTEXITCODE -ne 0) { throw "Tauri CLI installation failed." }

    & $Python -m PyInstaller `
        --noconfirm `
        --clean `
        --onefile `
        --noconsole `
        --name $sidecarName `
        --paths (Join-Path $projectDirectory "src") `
        --collect-data growth_mirror `
        --collect-all uvicorn `
        --distpath $sidecarDirectory `
        --workpath $pyInstallerWork `
        --specpath $specDirectory `
        $entrypoint
    if ($LASTEXITCODE -ne 0) { throw "Sidecar build failed." }

    $env:CARGO_TARGET_DIR = $CargoTargetDirectory
    npm run desktop:build
    if ($LASTEXITCODE -ne 0) { throw "Tauri installer build failed." }
} finally {
    Pop-Location
}

Write-Host "Installer output: $CargoTargetDirectory\release\bundle\nsis"
