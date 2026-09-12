@echo off
setlocal
cd /d "%~dp0"

rem Frozen regression markers for the prior visible-startup release:
rem desktop_v372.pyw
rem VERSION: 3.7.2

echo.
echo ===== BOSS VAO LENH V3 - DUNG BAN CU =====
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ports=45873,45874; foreach($p in $ports){ try { $c=New-Object Net.Sockets.TcpClient; $c.Connect('127.0.0.1',$p); $s=$c.GetStream(); $b=[Text.Encoding]::ASCII.GetBytes('EXIT'); $s.Write($b,0,$b.Length); $s.Dispose(); $c.Dispose() } catch {} }" >nul 2>&1
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
echo ===== CHAY TEST WINDOWS / LOGIC V3.7.3 =====
python -m unittest discover -s tests -v
if errorlevel 1 (
    echo.
    echo TEST LOI - KHONG BUILD EXE.
    pause
    exit /b 1
)

echo.
echo ===== BUILD BOSSVAOLENH V3.7.3 =====
pyinstaller --noconfirm --clean --onefile --windowed ^
  --name BossVaoLenh ^
  --collect-all pystray ^
  --collect-all tzdata ^
  desktop_v373.pyw

if errorlevel 1 (
    echo BUILD THAT BAI.
    pause
    exit /b 1
)

echo.
echo ===== BUILD THANH CONG =====
echo EXE: %CD%\dist\BossVaoLenh.exe
echo VERSION: 3.7.3
echo KHOI DONG: TOOL TU MO CUA SO MAT KHAU
echo BAO LENH: GIAY THU 10 CUA MOI PHIEN 5 PHUT
echo CHE DO DUY NHAT: COLOR ENGINE
echo TELEGRAM: BO TIEU DE TIN HIEU M5 + BO NUT CHON CHE DO
echo TELEGRAM: HIEN PHAN TICH CUNG HUONG X/6 + MAU NEN TRUOC O CUOI TIN
echo MUA NGAY: TU 3/6 CACH PHAN TICH CUNG HUONG
echo CHONG TRUNG TIN CHINH: KHOA ATOMIC THEO OPEN_TIME
echo 9 CHE DO CU: DA TAT - KHONG TAO MODE SIGNALS MOI
echo LICH SU: TOI DA 8640 NEN M5 - KHOANG 30 NGAY
echo 6 NGUON: KNN + CHUOI MAU + THAN NEN + VI TRI CLOSE + RAU NEN + REGIME
echo CHONG LEAK: KHONG DUNG GIA/BIEN DO NEN LIVE DE CHON MAU
echo SAU 2 LENH THUA: KHONG TAM NGHI 30 PHUT - GUI LIEN TUC
echo TELEGRAM DAU PHIEN: DUNG 2 TIN - 1 THE LENH + 1 TIN HANH DONG
echo KET QUA SAU 5 PHUT: 1 TIN THANG/THUA/HOA + HUONG + LENH 1/2
echo DATABASE CO DINH: %%LOCALAPPDATA%%\BossVaoLenh\data\bot.db
echo LOG: %%LOCALAPPDATA%%\BossVaoLenh\logs\boss-v3.log
echo.
echo Dang mo BAN V3.7.3 moi...
start "" "%CD%\dist\BossVaoLenh.exe"
echo.
echo V3.7.3 se hien cua so nhap mat khau ngay sau khi khoi dong.
echo Moi phien M5: 2 tin luc bat dau, 1 tin ket qua khi het 5 phut.
pause
