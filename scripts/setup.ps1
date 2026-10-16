[CmdletBinding()]
param([string]$PythonPath, [switch]$SkipNode)

$ErrorActionPreference = 'Stop'
$taskRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$taskVenv = Join-Path $taskRoot '.venv'
$taskPython = Join-Path $taskVenv 'Scripts/python.exe'
$taskTemp = Join-Path $taskRoot '.tmp'
$taskHelper = Join-Path $PSScriptRoot 'setup-support.py'

function Invoke-Checked {
    param([string]$Executable, [string[]]$Arguments)
    & $Executable @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Command failed with exit code ${LASTEXITCODE}: $Executable" }
}

if (-not $PythonPath) {
    # Discover the base interpreter independently of a possibly broken existing .venv.
    $taskCandidate = (Get-Command python.exe -ErrorAction SilentlyContinue).Source
    if (-not $taskCandidate) { $taskCandidate = (Get-Command py.exe -ErrorAction Stop).Source }
    $PythonPath = & $taskCandidate $taskHelper base
    if ($LASTEXITCODE -ne 0) { throw 'Provide a working base Python executable with -PythonPath.' }
    $PythonPath = $PythonPath | Select-Object -Last 1
}
$PythonPath = (Resolve-Path -LiteralPath $PythonPath).Path
$taskBaseVersion = & $PythonPath $taskHelper version
if ($LASTEXITCODE -ne 0) { throw 'Python 3.11 or newer required.' }

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
            # Native stderr becomes a terminating error under Windows PowerShell 5.1.
            $ErrorActionPreference = 'Continue'
            $taskEnvVersion = & $taskPython $taskHelper version 2>$null
            if ($LASTEXITCODE -eq 0 -and $taskEnvVersion -eq $taskBaseVersion) {
                # Missing packages are installed below; broken native imports require a clean environment.
                & $taskPython $taskHelper probe 2>$null
                $taskValid = $LASTEXITCODE -eq 0
            }
            $ErrorActionPreference = 'Stop'
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
        Invoke-Checked $PythonPath @('-m', 'venv', $taskVenv)
    }
    Invoke-Checked $taskPython @('-m', 'ensurepip', '--upgrade')
    Invoke-Checked $taskPython @('-m', 'pip', 'install', '--cache-dir', '.tmp/pip-cache', '--upgrade', 'pip')
    Invoke-Checked $taskPython @('-m', 'pip', 'install', '--cache-dir', '.tmp/pip-cache', '-e', '.[dev]', '-e', './frontend/image-context[test]')
    Invoke-Checked $taskPython @('-m', 'pip', 'check')
    Invoke-Checked $taskPython @($taskHelper, 'verify')
    Invoke-Checked $taskPython @($taskHelper, 'configure')
    if (-not $SkipNode) {
        $taskNpm = (Get-Command npm.cmd -ErrorAction Stop).Source
        foreach ($taskProject in @('frontend', 'extension', 'reddit-bot')) {
            Invoke-Checked $taskNpm @('--prefix', $taskProject, 'ci', '--cache', (Join-Path $taskTemp 'npm-cache'))
        }
    }
    Write-Host 'Setup complete. Run scripts\setup-model.cmd for the local vision model.'
} finally {
    $env:TEMP = $taskOldTemp
    $env:TMP = $taskOldTmp
    Pop-Location
}
