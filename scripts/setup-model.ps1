[CmdletBinding()]
param([string]$Model = 'qwen3-vl:4b-instruct')

$ErrorActionPreference = 'Stop'
$taskRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$taskOllama = (Get-Command ollama -ErrorAction SilentlyContinue).Source
if (-not $taskOllama) {
    $taskOllama = Join-Path $env:USERPROFILE 'AppData/Local/Programs/Ollama/ollama.exe'
}
if (-not (Test-Path -LiteralPath $taskOllama)) {
    throw 'Install Ollama for Windows, then run this command again.'
}
$taskPython = Join-Path $taskRoot '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $taskPython)) { throw 'Run scripts/setup.cmd first.' }
New-Item -ItemType Directory -Force -Path (Join-Path $taskRoot '.tmp') | Out-Null
try { $null = Invoke-RestMethod 'http://127.0.0.1:11434/api/tags' -TimeoutSec 3 } catch {
    Start-Process -FilePath $taskOllama -ArgumentList 'serve' -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $taskRoot '.tmp/ollama-server.log') `
        -RedirectStandardError (Join-Path $taskRoot '.tmp/ollama-server-error.log')
    $taskDeadline = [DateTime]::UtcNow.AddSeconds(20)
    while ($true) {
        try { $null = Invoke-RestMethod 'http://127.0.0.1:11434/api/tags' -TimeoutSec 2; break } catch {
            if ([DateTime]::UtcNow -gt $taskDeadline) { throw 'Ollama did not start. Check .tmp/ollama-server-error.log.' }
            Start-Sleep -Milliseconds 300
        }
    }
}
& $taskOllama pull $Model
if ($LASTEXITCODE -ne 0) { throw 'Local model download failed.' }
Push-Location $taskRoot
try {
    & $taskPython (Join-Path $PSScriptRoot 'setup-support.py') configure --model $Model
    if ($LASTEXITCODE -ne 0) { throw 'Could not configure local model settings.' }
} finally { Pop-Location }
