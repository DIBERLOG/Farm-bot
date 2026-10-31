@echo off
cd /d "%~dp0"
if not exist "warpath-helper.exe" call build.bat
if not exist "warpath-helper.exe" exit /b 1
start "" "%~dp0warpath-helper.exe" %*
