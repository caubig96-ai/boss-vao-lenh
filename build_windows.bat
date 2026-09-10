@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    py -3 -m venv .venv
)

call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements-windows.txt

 echo.
echo ===== CHAY TEST TRUOC KHI BUILD =====
python -m unittest discover -s tests -v
if errorlevel 1 (
    echo.
    echo TEST LOI - KHONG BUILD EXE DE TRANH GHI DE BAN DANG CHAY.
    pause
    exit /b 1
)

 echo.
echo ===== BUILD BOSSVAOLENH.EXE =====
pyinstaller --noconfirm --clean --onefile --windowed ^
  --name BossVaoLenh ^
  --collect-all pystray ^
  --collect-all tzdata ^
  desktop_tray.pyw

if errorlevel 1 (
    echo BUILD THAT BAI.
    pause
    exit /b 1
)

echo.
echo Da tao: dist\BossVaoLenh.exe
echo Du lieu thong ke Windows duoc luu rieng trong LocalAppData\BossVaoLenh\data\bot.db
echo Khi thay EXE moi, thong ke cu se khong bi mat do doi thu muc EXE.
pause
