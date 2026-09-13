@echo off
setlocal
python -m pip install --upgrade pip
python -m pip install -r requirements-windows.txt
python -m PyInstaller --noconfirm --clean --windowed --name BossVaoLenh desktop_v378.pyw
endlocal
