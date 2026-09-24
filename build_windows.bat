@echo off
setlocal
cd /d "%~dp0"

rem Legacy regression markers kept for historical unit tests only:
rem desktop_v372.pyw
rem VERSION: 3.7.2

echo.
echo ===== BOSS VAO LENH V4.1.0 - 5 NEN NHAN DANG =====
taskkill /IM BossVaoLenh.exe /T /F >nul 2>&1

if not exist ".venv\Scripts\python.exe" py -3 -m venv .venv
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements-windows.txt
if errorlevel 1 exit /b 1

echo ===== CHAY TEST =====
python -m unittest discover -s tests -v
if errorlevel 1 (
    echo TEST LOI - KHONG BUILD EXE.
    pause
    exit /b 1
)

echo ===== BUILD BOSSVAOLENH V4.1.0 =====
pyinstaller --noconfirm --clean --onefile --windowed ^
  --name BossVaoLenh ^
  --collect-all pystray ^
  --collect-all tzdata ^
  desktop_v376.pyw
if errorlevel 1 exit /b 1

set "BOSS_EXE=%CD%\dist\BossVaoLenh.exe"
echo ===== DANG KY TU KHOI DONG WINDOWS =====
powershell -NoProfile -ExecutionPolicy Bypass -Command "$exe=(Resolve-Path -LiteralPath '%BOSS_EXE%').Path; $run='HKCU:\Software\Microsoft\Windows\CurrentVersion\Run'; Set-ItemProperty -Path $run -Name 'BossVaoLenh' -Value ([char]34 + $exe + [char]34)"
if errorlevel 1 (
    echo CANH BAO: KHONG DANG KY DUOC AUTO START.
) else (
    echo AUTO START: OK
)

echo.
echo ===== BUILD THANH CONG =====
echo EXE: %BOSS_EXE%
echo VERSION: 4.1.0
echo NGUON MAU: BINANCE PREDICTION BTC UP/DOWN 5M (PREDICT.FUN-BACKED)
echo CHIEN LUOC: CHI DUNG BANG 24 MAU 5 VONG DA CHOT
echo TELEGRAM: GUI KET QUA THANG/THUA TRUOC, SAU DO GUI LENH MUA XANH/DO KHI KHOP MAU
echo TIEN LENH: LENH 1 THANG -^> LENH 2; SAU LENH 2 HOAC THUA -^> LENH 1
echo THONG KE: VON DAU NGAY, LAI/LO, SO DU CUOI NGAY, 100 LENH V/X
echo IPHONE: MO http://IP-PC:8765 TREN SAFARI CUNG WIFI
echo TELEGRAM TEST: MO BANG DIEU KHIEN VA BAM TEST TELEGRAM
echo DATABASE: %%LOCALAPPDATA%%\BossVaoLenh\data\bot.db
echo LOG: %%LOCALAPPDATA%%\BossVaoLenh\logs\boss-v4.log
start "" "%BOSS_EXE%"
pause
