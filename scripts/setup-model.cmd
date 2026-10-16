@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup-model.ps1" %*
exit /b %errorlevel%
