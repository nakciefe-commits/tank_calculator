@echo off
REM Tank Cascade Doldurma Hesaplayici - Windows baslatici
REM Python kurulu degilse uyarir, kuruluysa bagimliliklari kurup uygulamayi acar.

setlocal
cd /d "%~dp0"

REM 1) Python var mi?
where python >nul 2>&1
if errorlevel 1 (
    where py >nul 2>&1
    if errorlevel 1 (
        echo.
        echo HATA: Python bulunamadi.
        echo.
        echo Lutfen Python 3.9+ kurun: https://www.python.org/downloads/
        echo Kurulum sirasinda "Add Python to PATH" secenegini isaretleyin.
        echo.
        pause
        exit /b 1
    ) else (
        set "PY=py"
    )
) else (
    set "PY=python"
)

echo.
echo Tank Cascade Doldurma Hesaplayici baslatiliyor...
echo Python:
%PY% --version
echo.

REM 2) app.py icindeki bootstrap eksik paketleri kuracak; yine de
REM    burada bir on-kontrol yapalim ki ilk kosumda log gorsun.
%PY% -c "import CoolProp, scipy, numpy" 2>nul
if errorlevel 1 (
    echo Eksik kutuphaneler tespit edildi. Kuruluyor...
    %PY% -m pip install --user --upgrade -r requirements.txt
    if errorlevel 1 (
        echo.
        echo HATA: Kutuphaneler kurulamadi. Internet baglantinizi kontrol edin.
        pause
        exit /b 1
    )
)

REM 3) Uygulamayi calistir (pencereli, konsolsuz)
start "" pythonw app.py 2>nul
if errorlevel 1 (
    %PY% app.py
)

endlocal
