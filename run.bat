
@echo off
chcp 65001 >nul
cd /d "%~dp0"
title AI Crypto Trading Firm

set "PYTHON=%~dp0venv\Scripts\python.exe"

echo ==========================================
echo       AI Crypto Trading Firm
echo ==========================================

if not exist "%PYTHON%" (
    echo [1/4] Creating virtual environment...
    python -m venv venv
    if errorlevel 1 (
        echo ERROR: Could not create virtual environment.
        pause
        exit /b 1
    )
)

echo.
echo [2/4] Installing core requirements...
"%PYTHON%" -m pip install -r requirements.txt
if errorlevel 1 (
    echo ERROR: Core requirements installation failed.
    pause
    exit /b 1
)

echo.
echo [3/4] Installing MT5 requirements...
"%PYTHON%" -m pip install -r requirements-window.txt
if errorlevel 1 (
    echo WARNING: Windows requirements installation failed.
)

echo Installing MetaTrader5 explicitly...
"%PYTHON%" -m pip install MetaTrader5
if errorlevel 1 (
    echo ERROR: MetaTrader5 installation failed.
    pause
    exit /b 1
)

echo.
echo Checking MetaTrader5...
"%PYTHON%" -c "import MetaTrader5 as mt5; print('MT5 OK:', mt5.__version__)"
if errorlevel 1 (
    echo ERROR: MetaTrader5 cannot be imported.
    pause
    exit /b 1
)

echo.
echo Installing optional AI requirements...
"%PYTHON%" -m pip install -r requirements-ai.txt

if not exist .env copy .env.example .env >nul

echo.
echo [4/4] Starting application...
"%PYTHON%" app.py

echo.
echo Application stopped.
pause
