@echo off
setlocal
cd /d "%~dp0"

where pythonw.exe >nul 2>nul
if errorlevel 1 (
    echo ARC3 could not find Python.
    echo Install Python or add pythonw.exe to PATH, then try again.
    pause
    exit /b 1
)

start "ARC3 Toolkit" pythonw.exe "%~dp0arc3.py"
exit /b 0
