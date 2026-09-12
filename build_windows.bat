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
echo ===== CHAY TEST WINDOWS / LOGIC V3.6.1 =====
python -m unittest discover -s tests -v
if errorlevel 1 (
    echo.
    echo TEST LOI - KHONG BUILD EXE.
    pause
    exit /b 1
)

echo.
echo ===== BUILD BOSSVAOLENH V3.6.1 =====
pyinstaller --noconfirm --clean --onefile --windowed ^
  --name BossVaoLenh ^
  --collect-all pystray ^
  --collect-all tzdata ^
  desktop_v361.pyw

if errorlevel 1 (
    echo BUILD THAT BAI.
    pause
    exit /b 1
)

echo.
echo ===== BUILD THANH CONG =====
echo EXE: %CD%\dist\BossVaoLenh.exe
echo VERSION: 3.6.1
echo BAO LENH: GIAY THU 10 CUA MOI PHIEN 5 PHUT
echo NGUON NEN: BINANCE FUTURES KLINE M1/M5 ONLY
echo AUTO MODE: NEU MODE DU MAU CO WR DUOI 50 PHAN TRAM THI TU DAO TANG/GIAM
echo XEP HANG: DUNG TY LE HIEU DUNG SAU DAO DE CHON MODE
ECHO DONG THUAN: HUONG CHON + CHUOI GAN DAY + PHIEU CAC MODE PHAI CUNG HUONG MOI MUA NGAY
echo SAU 2 LENH THUA: KHONG TAM NGHI 30 PHUT - GUI LIEN TUC
echo TELEGRAM DAU PHIEN: DUNG 2 TIN - 1 TIN HIEU + 1 TIN HANH DONG
echo CAP THANG/THUA: CHI TINH 2 LENH CUNG KET QUA LIEN NHAU THEO THOI GIAN
echo TIN HIEU: GIU NGUYEN TOAN BO NUT CU + NUT CHI TIET
echo TIN 2: CHI MUA NGAY KHI CAC NGUON CUNG HUONG; NEU KHONG THI KHONG NEN VAO
echo KET QUA SAU 5 PHUT: 1 TIN THANG/THUA/HOA + HUONG + LENH 1/2
echo DATABASE CO DINH: %%LOCALAPPDATA%%\BossVaoLenh\data\bot.db
echo LOG: %%LOCALAPPDATA%%\BossVaoLenh\logs\boss-v3.log
echo.
echo Dang mo BAN V3.6.1 moi...
start "" "%CD%\dist\BossVaoLenh.exe"
echo.
echo Moi phien M5: 2 tin luc bat dau, 1 tin ket qua khi het 5 phut.
pause
