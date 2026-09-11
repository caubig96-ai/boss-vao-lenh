@echo off
setlocal
cd /d "%~dp0"

echo.
echo ===== BOSS VAO LENH V3 - DUNG BAN CU =====
py -3 -c "import socket,time; [(lambda p: (lambda s: (s.settimeout(.3),s.connect(('127.0.0.1',p)),s.sendall(b'EXIT'),s.close()))(socket.socket()))(p) for p in (45873,45874) if True]" >nul 2>&1
timeout /t 2 /nobreak >nul
taskkill /IM BossVaoLenh.exe /T /F >nul 2>&1

if exist ".env" (
    echo ===== DAT THOI DIEM BAO LENH = GIAY THU 10 =====
    powershell -NoProfile -ExecutionPolicy Bypass -Command "$p='.env'; $lines=Get-Content -LiteralPath $p; if($lines -match '^DECISION_SECOND='){ $lines=$lines -replace '^DECISION_SECOND=.*$','DECISION_SECOND=10' } else { $lines += 'DECISION_SECOND=10' }; Set-Content -LiteralPath $p -Value $lines -Encoding UTF8"
)

if not exist ".venv\Scripts\python.exe" (
    py -3 -m venv .venv
)

call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements-windows.txt
if errorlevel 1 (
    echo.
    echo LOI CAI THU VIEN - DUNG BUILD.
    pause
    exit /b 1
)

echo.
echo ===== CHAY TEST WINDOWS / LOGIC V3.5.2 =====
python -m unittest discover -s tests -v
if errorlevel 1 (
    echo.
    echo TEST LOI - KHONG BUILD EXE.
    pause
    exit /b 1
)

echo.
echo ===== BUILD BOSSVAOLENH V3.5.2 =====
pyinstaller --noconfirm --clean --onefile --windowed ^
  --name BossVaoLenh ^
  --collect-all pystray ^
  --collect-all tzdata ^
  desktop_v352.pyw

if errorlevel 1 (
    echo BUILD THAT BAI.
    pause
    exit /b 1
)

echo.
echo ===== BUILD THANH CONG =====
echo EXE: %CD%\dist\BossVaoLenh.exe
echo VERSION: 3.5.2
echo BAO LENH: GIAY THU 10 CUA MOI PHIEN 5 PHUT
echo NGUON NEN: BINANCE FUTURES KLINE M1/M5 ONLY
echo TIN NHAN: NGAN GON + NUT CHI TIET
echo MOI M5: VAN GUI MUA TANG/GIAM KHI BOT DANG CHAY
echo NEN VAO: GUI THEM MUA TANG/GIAM NGAY
echo KET QUA: CHI BAO THANG/THUA/HOA + HUONG + LENH 1/2
echo DATABASE CO DINH: %%LOCALAPPDATA%%\BossVaoLenh\data\bot.db
echo LOG: %%LOCALAPPDATA%%\BossVaoLenh\logs\boss-v3.log
echo.
echo Dang mo BAN V3.5.2 moi...
start "" "%CD%\dist\BossVaoLenh.exe"
echo.
echo Tin hieu ngan gon; bam CHI TIET tren Telegram de xem phan tich day du.
pause
