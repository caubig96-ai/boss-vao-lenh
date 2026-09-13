@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\pythonw.exe" (
    echo [LOI] Chua co .venv. Hay chay build_windows.bat truoc.
    pause
    exit /b 1
)

rem Run the desktop source through the already-trusted Python interpreter.
rem This is the fallback for PCs where Device Guard blocks unsigned PyInstaller EXEs.
start "BossVaoLenh V3.8.1" /B ".venv\Scripts\pythonw.exe" "desktop_v381.pyw"
exit /b 0
