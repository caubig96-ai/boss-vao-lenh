@echo off
setlocal
cd /d "%~dp0"

rem Frozen regression markers for prior visible-startup releases:
rem desktop_v372.pyw
rem VERSION: 3.7.2

echo.
echo ===== BOSS VAO LENH V3 - DUNG BAN CU =====
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ports=45873,45874; foreach($p in $ports){ try { $c=New-Object Net.Sockets.TcpClient; $c.Connect('127.0.0.1',$p); $s=$c.GetStream(); $b=[Text.Encoding]::ASCII.GetBytes('EXIT'); $s.Write($b,0,$b.Length); $s.Dispose(); $c.Dispose() } catch {} }" >nul 2>&1
timeout /t 2 /nobreak >nul
taskkill /IM BossVaoLenh.exe /T /F >nul 2>&1

if exist ".env" (
    powershell -NoProfile -ExecutionPolicy Bypass -Command "$p='.env'; $lines=Get-Content -LiteralPath $p; if($lines -match '^DECISION_SECOND='){ $lines=$lines -replace '^DECISION_SECOND=.*$','DECISION_SECOND=10' } else { $lines += 'DECISION_SECOND=10' }; Set-Content -LiteralPath $p -Value $lines -Encoding UTF8"
)

if not exist ".venv\Scripts\python.exe" py -3 -m venv .venv
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements-windows.txt
if errorlevel 1 exit /b 1

echo ===== CHAY TEST WINDOWS / LOGIC V3.7.8 =====
python -m unittest discover -s tests -v
if errorlevel 1 (
    echo TEST LOI - KHONG BUILD EXE.
    pause
    exit /b 1
)

echo ===== BUILD BOSSVAOLENH V3.7.8 =====
pyinstaller --noconfirm --clean --onefile --windowed ^
  --name BossVaoLenh ^
  --collect-all pystray ^
  --collect-all tzdata ^
  desktop_v378.pyw
if errorlevel 1 exit /b 1

echo.
echo ===== BUILD THANH CONG =====
echo EXE: %CD%\dist\BossVaoLenh.exe
echo VERSION: 3.7.8
echo 6 PHUONG PHAP DOC LAP - KHONG DUNG NGUONG X/6
echo THONG KE GOC KHONG DAO; CHI DAO HUONG LENH GUI
echo CUA SO 100 DU BAO - TOI THIEU 30 THANG/THUA
echo CHUA DU DIEU KIEN = KHONG MUA
echo DATABASE: %%LOCALAPPDATA%%\BossVaoLenh\data\bot.db
echo LOG: %%LOCALAPPDATA%%\BossVaoLenh\logs\boss-v3.log
start "" "%CD%\dist\BossVaoLenh.exe"
pause
