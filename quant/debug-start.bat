@echo off
setlocal enabledelayedexpansion
set "ROOT=%~dp0"
cd /d "%ROOT%"

set "PYTHON313_EXE=%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
set "VENV_DIR=%ROOT%.venv"
set "VENV_PYTHON_EXE=%VENV_DIR%\Scripts\python.exe"
set "NEED_VENV_REPAIR=0"
set "LOG=%ROOT%debug_start.log"

echo === Diagnostic Start === > "%LOG%"
echo ROOT=%ROOT% >> "%LOG%"
if not exist "%VENV_PYTHON_EXE%" (
    set "NEED_VENV_REPAIR=1"
)
if exist "%VENV_PYTHON_EXE%" (
    "%VENV_PYTHON_EXE%" -c "import sys" >> "%LOG%" 2>&1
    if !errorlevel! neq 0 set "NEED_VENV_REPAIR=1"
)

if "%NEED_VENV_REPAIR%"=="1" (
    if exist "%PYTHON313_EXE%" (
        set "BASE_PYTHON_EXE=%PYTHON313_EXE%"
    ) else (
        for /f "delims=" %%i in ('where python 2^>nul') do (
            if not defined BASE_PYTHON_EXE set "BASE_PYTHON_EXE=%%i"
        )
    )

    if not defined BASE_PYTHON_EXE (
        echo ERROR: Python 3.13 not found at %PYTHON313_EXE%, and no python.exe was found on PATH. >> "%LOG%"
        type "%LOG%"
        pause
        exit /b 1
    )

    if exist "%VENV_PYTHON_EXE%" (
        echo Repairing .venv with !BASE_PYTHON_EXE! >> "%LOG%"
        "!BASE_PYTHON_EXE!" -m venv --upgrade "%VENV_DIR%" >> "%LOG%" 2>&1
    ) else (
        echo Creating .venv with !BASE_PYTHON_EXE! >> "%LOG%"
        "!BASE_PYTHON_EXE!" -m venv "%VENV_DIR%" >> "%LOG%" 2>&1
    )
    if !errorlevel! neq 0 (
        echo ERROR: Failed to create virtual environment at %VENV_DIR%. >> "%LOG%"
        type "%LOG%"
        pause
        exit /b 1
    )
)

if not exist "%VENV_PYTHON_EXE%" (
    echo ERROR: Python not found at %VENV_PYTHON_EXE%. >> "%LOG%"
    type "%LOG%"
    pause
    exit /b 1
)

"%VENV_PYTHON_EXE%" -c "import sys" >> "%LOG%" 2>&1
if errorlevel 1 (
    echo ERROR: Virtual environment Python is still not usable at %VENV_PYTHON_EXE%. >> "%LOG%"
    type "%LOG%"
    pause
    exit /b 1
)

set "PYTHON_EXE=%VENV_PYTHON_EXE%"
echo PYTHON_EXE=%PYTHON_EXE% >> "%LOG%"
echo PYTHON_EXE exists=1 >> "%LOG%"

"%PYTHON_EXE%" -c "import uvicorn, fastapi, pandas, numpy" >> "%LOG%" 2>&1
if errorlevel 1 (
    echo Installing backend dependencies into .venv... >> "%LOG%"
    "%PYTHON_EXE%" -m pip install -r "%ROOT%backend\requirements.txt" >> "%LOG%" 2>&1
    if !ERRORLEVEL! neq 0 (
        echo ERROR: Failed to install backend dependencies into .venv. >> "%LOG%"
        type "%LOG%"
        pause
        exit /b 1
    )
)

echo Step 1: Test Python... >> "%LOG%"
"%PYTHON_EXE%" -c "print('Python OK')" >> "%LOG%" 2>&1
echo Python exit code=%ERRORLEVEL% >> "%LOG%"

echo Step 2: Test basic import... >> "%LOG%"
"%PYTHON_EXE%" -c "import sys; print('sys OK'); import pandas; print('pandas OK')" >> "%LOG%" 2>&1
echo Import exit code=%ERRORLEVEL% >> "%LOG%"

echo Step 3: Test backend import... >> "%LOG%"
"%PYTHON_EXE%" -c "import sys; sys.path.insert(0,'.'); from backend.market.aggregator import kline_to_chart_data; print('aggregator OK')" >> "%LOG%" 2>&1
echo Aggregator exit code=%ERRORLEVEL% >> "%LOG%"

echo Step 4: Test kline_parquet import... >> "%LOG%"
"%PYTHON_EXE%" -c "import sys; sys.path.insert(0,'.'); from backend.kline_parquet import get_kline_parquet; print('kline_parquet OK')" >> "%LOG%" 2>&1
echo kline_parquet exit code=%ERRORLEVEL% >> "%LOG%"

echo Step 5: Test kline_service import... >> "%LOG%"
"%PYTHON_EXE%" -c "import sys; sys.path.insert(0,'.'); from backend.kline_service import ensure_local_kline_cache; print('kline_service OK')" >> "%LOG%" 2>&1
echo kline_service exit code=%ERRORLEVEL% >> "%LOG%"

echo Step 6: Test main import... >> "%LOG%"
"%PYTHON_EXE%" -c "import sys; sys.path.insert(0,'.'); from backend.main import app; print('main OK')" >> "%LOG%" 2>&1
echo main exit code=%ERRORLEVEL% >> "%LOG%"

echo === Done === >> "%LOG%"
type "%LOG%"
echo.
echo Log saved to: %LOG%
pause
