@echo off
setlocal
start "" powershell.exe -NoProfile -ExecutionPolicy Bypass -STA -WindowStyle Hidden -File "%~dp0Builder.ps1" %*
exit /b
