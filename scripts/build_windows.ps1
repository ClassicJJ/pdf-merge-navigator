$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$venv = Join-Path $projectRoot ".venv"
$venvPython = Join-Path $venv "Scripts\python.exe"
$outputDir = Join-Path $projectRoot "output"
$exePath = Join-Path $outputDir "PDF-Merge-Navigator.exe"
$iconPath = Join-Path $projectRoot "assets\app-icon.ico"
$iconData = "$iconPath;assets"

function Stop-ReleaseProcesses {
    param([string]$ExecutablePath)
    $processName = [System.IO.Path]::GetFileNameWithoutExtension(
        $ExecutablePath
    )
    Get-Process -Name $processName -ErrorAction SilentlyContinue |
        Where-Object {
            try {
                $_.Path -eq $ExecutablePath
            }
            catch {
                $false
            }
        } |
        Stop-Process -Force
}

if (-not (Test-Path -LiteralPath $venvPython)) {
    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if ($null -ne $pythonCommand) {
        & $pythonCommand.Source -m venv $venv
    }
    else {
        $pythonLauncher = Get-Command py -ErrorAction Stop
        & $pythonLauncher.Source -3 -m venv $venv
    }
}

& $venvPython -m pip install --disable-pip-version-check -r (Join-Path $projectRoot "requirements-build.txt")
if ($LASTEXITCODE -ne 0) {
    throw "Dependency installation failed."
}

$env:PYTHONPATH = Join-Path $projectRoot "src"
& $venvPython -X utf8 -m pytest (Join-Path $projectRoot "tests") -q
if ($LASTEXITCODE -ne 0) {
    throw "Tests failed. Build stopped."
}

Push-Location $projectRoot
try {
    & $venvPython -m PyInstaller `
        --noconfirm `
        --clean `
        --log-level WARN `
        --onefile `
        --windowed `
        --icon $iconPath `
        --add-data $iconData `
        --name "PDF-Merge-Navigator" `
        --paths (Join-Path $projectRoot "src") `
        --additional-hooks-dir (Join-Path $projectRoot "scripts\pyinstaller-hooks") `
        --distpath $outputDir `
        --workpath (Join-Path $projectRoot "build") `
        --specpath (Join-Path $projectRoot "build") `
        (Join-Path $projectRoot "run_tool.py")
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller build failed."
    }
}
finally {
    Pop-Location
}

Copy-Item -LiteralPath (Join-Path $projectRoot "README.md") -Destination $outputDir -Force
Copy-Item -LiteralPath (Join-Path $projectRoot "THIRD-PARTY-NOTICES.txt") -Destination $outputDir -Force

& $venvPython -X utf8 (Join-Path $projectRoot "scripts\validate_release.py") --exe $exePath
if ($LASTEXITCODE -ne 0) {
    throw "Release validation failed."
}

$releaseProcess = Start-Process -FilePath $exePath -WindowStyle Hidden -PassThru
try {
    Start-Sleep -Seconds 4
    if ($releaseProcess.HasExited) {
        throw "Built EXE exited during the hidden cold-start check."
    }
}
finally {
    Stop-ReleaseProcesses -ExecutablePath $exePath
}

Write-Host "Built and verified: $exePath"
