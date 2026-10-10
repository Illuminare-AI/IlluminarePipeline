[CmdletBinding()]
param([string]$PythonPath)

$ErrorActionPreference = 'Stop'
$taskRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$taskVenv = Join-Path $taskRoot '.venv'
$taskPython = Join-Path $taskVenv 'Scripts/python.exe'
$taskTemp = Join-Path $taskRoot '.tmp'

function Invoke-Checked {
    param([string]$Executable, [string[]]$Arguments)
    & $Executable @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Command failed with exit code ${LASTEXITCODE}: $Executable" }
}

if (-not $PythonPath) {
    $taskCandidate = if (Test-Path -LiteralPath $taskPython) { $taskPython } else { (Get-Command python -ErrorAction Stop).Source }
    $PythonPath = & $taskCandidate -c 'import sys; print(sys._base_executable)'
    if ($LASTEXITCODE -ne 0) { throw 'Provide a working base Python executable with -PythonPath.' }
    $PythonPath = $PythonPath | Select-Object -Last 1
}
$PythonPath = (Resolve-Path -LiteralPath $PythonPath).Path
Invoke-Checked $PythonPath @('-c', 'import sys; assert sys.version_info >= (3, 11), "Python 3.11 or newer required"; import pip')
$taskBaseVersion = & $PythonPath -c 'import sys; print("%s.%s" % sys.version_info[:2])'

New-Item -ItemType Directory -Force -Path $taskTemp | Out-Null
$taskOldTemp = $env:TEMP
$taskOldTmp = $env:TMP
Push-Location $taskRoot
try {
    $env:TEMP = $taskTemp
    $env:TMP = $taskTemp
    if (Test-Path -LiteralPath $taskVenv) {
        $taskValid = $false
        if (Test-Path -LiteralPath $taskPython) {
            $taskEnvVersion = & $taskPython -c 'import sys; print("%s.%s" % sys.version_info[:2])' 2>$null
            if ($LASTEXITCODE -eq 0 -and $taskEnvVersion -eq $taskBaseVersion) {
                # Missing packages are installed below; broken native imports require a clean environment.
                & $taskPython -c 'import importlib.util; modules = ["PIL.Image", "pydantic_core", "numpy", "scipy"]; [__import__(m) for m in modules if importlib.util.find_spec(m.split(".")[0])]' 2>$null
                $taskValid = $LASTEXITCODE -eq 0
            }
        }
        if (-not $taskValid) {
            $taskSource = (Resolve-Path -LiteralPath $taskVenv).Path
            $taskBackup = [IO.Path]::GetFullPath((Join-Path $taskTemp ('venv-before-repair-' + [Guid]::NewGuid().ToString('N'))))
            $taskPrefix = $taskRoot + [IO.Path]::DirectorySeparatorChar
            if (-not $taskSource.StartsWith($taskPrefix, [StringComparison]::OrdinalIgnoreCase) -or
                -not $taskBackup.StartsWith($taskPrefix, [StringComparison]::OrdinalIgnoreCase)) {
                throw 'Environment backup paths must stay inside this repository.'
            }
            Move-Item -LiteralPath $taskSource -Destination $taskBackup
            Write-Host "Saved the incompatible environment in $taskBackup"
        }
    }
    if (-not (Test-Path -LiteralPath $taskPython)) {
        Invoke-Checked $PythonPath @('-m', 'venv', '--without-pip', $taskVenv)
    }
    Invoke-Checked $PythonPath @('-m', 'pip', '--python', $taskPython, 'install', '--cache-dir', '.tmp/pip-cache', 'pip', '-e', '.[dev]', '-e', './frontend/image-context[test]')
    Invoke-Checked $taskPython @('-m', 'pip', 'check')
    Invoke-Checked $taskPython @('-c', 'from PIL import Image; import pydantic_core, scipy, factcheck.api, image_context.api; print("Backend, OCR and native imports verified")')
    Write-Host 'Setup complete. Both Python services are installed in the root .venv.'
} finally {
    $env:TEMP = $taskOldTemp
    $env:TMP = $taskOldTmp
    Pop-Location
}
