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
if (-not (Test-Path -LiteralPath $taskPython)) { throw 'Run scripts/setup.ps1 first.' }
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
    & $taskPython -c @'
import sys
import re
from pathlib import Path
model = sys.argv[1]
for name in ('.env', 'frontend/image-context/.env'):
    path = Path(name)
    if not path.exists():
        example = path.with_name('.env.example')
        path.write_text(example.read_text() if example.exists() else '', encoding='utf-8')
def update_env(name, updates):
    path = Path(name)
    lines = path.read_text(encoding='utf-8').splitlines()
    remaining = dict(updates)
    for index, line in enumerate(lines):
        match = re.match(r'^\s*(?:export\s+)?([A-Za-z_][A-Za-z_0-9]*)\s*=', line)
        if match and match[1] in updates:
            key = match[1]
            lines[index] = f"{key}='{updates[key]}'"
            remaining.pop(key, None)
    lines.extend(f"{key}='{value}'" for key, value in remaining.items())
    # Write once; repeated atomic replacements can fail on Windows while scanners hold the file.
    path.write_text('\n'.join(lines) + '\n', encoding='utf-8')
update_env('.env', {'IMAGE_CONTEXT_URL': 'http://127.0.0.1:8001', 'IMAGE_VISION_ENABLED': 'true', 'IMAGE_CONTEXT_TIMEOUT': '600'})
updates = {'OLLAMA_URL': 'http://127.0.0.1:11434', 'VISION_MODEL': model, 'VISION_ENABLED': 'true', 'VISION_TIMEOUT': '540'}
tesseract = Path('C:/Program Files/Tesseract-OCR/tesseract.exe')
if tesseract.is_file():
    updates['TESSERACT_CMD'] = tesseract.as_posix()
update_env('frontend/image-context/.env', updates)
print('Local image model configured. Start the three services from README-QUICKSTART.md.')
'@ $Model
    if ($LASTEXITCODE -ne 0) { throw 'Could not configure local model settings.' }
} finally { Pop-Location }
