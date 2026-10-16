@echo off
if not exist "%~dp0..\.venv\Scripts\python.exe" (
  echo Run scripts\setup.cmd first.
  exit /b 1
)
"%~dp0..\.venv\Scripts\python.exe" "%~dp0start-local.py" %*
exit /b %errorlevel%
