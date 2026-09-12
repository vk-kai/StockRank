@echo off
setlocal enabledelayedexpansion
set "ROOT=%~dp0"
cd /d "%ROOT%"

echo === Stopping existing processes ===

REM Kill processes on port 8000
for /f "tokens=5" %%i in ('netstat -ano 2^>nul ^| findstr /r "\b:8000\b"') do (
    echo Killing PID %%i on port 8000
    taskkill /F /PID %%i >nul 2>&1
)

REM Kill processes on port 5173
for /f "tokens=5" %%i in ('netstat -ano 2^>nul ^| findstr /r "\b:5173\b"') do (
    echo Killing PID %%i on port 5173
    taskkill /F /PID %%i >nul 2>&1
)

timeout /t 2 /nobreak >nul

set "PYTHON313_EXE=%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
set "VENV_DIR=%ROOT%.venv"
set "VENV_PYTHON_EXE=%VENV_DIR%\Scripts\python.exe"
set "NEED_VENV_REPAIR=0"

if not exist "%VENV_PYTHON_EXE%" (
    set "NEED_VENV_REPAIR=1"
)
if exist "%VENV_PYTHON_EXE%" (
    "%VENV_PYTHON_EXE%" -c "import sys" >nul 2>&1
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
        echo ERROR: Python 3.13 not found at %PYTHON313_EXE%, and no python.exe was found on PATH.
        pause
        exit /b 1
    )

    if exist "%VENV_PYTHON_EXE%" (
        echo Virtual environment is not healthy. Repairing .venv with: !BASE_PYTHON_EXE!
        "!BASE_PYTHON_EXE!" -m venv --upgrade "%VENV_DIR%"
    ) else (
        echo Virtual environment not found. Creating .venv with: !BASE_PYTHON_EXE!
        "!BASE_PYTHON_EXE!" -m venv "%VENV_DIR%"
    )
    if !errorlevel! neq 0 (
        echo ERROR: Failed to create virtual environment at %VENV_DIR%.
        pause
        exit /b 1
    )
)

if not exist "%VENV_PYTHON_EXE%" (
    echo ERROR: Python not found at %VENV_PYTHON_EXE%.
    pause
    exit /b 1
)
"%VENV_PYTHON_EXE%" -c "import sys" >nul 2>&1
if errorlevel 1 (
    echo ERROR: Virtual environment Python is still not usable at %VENV_PYTHON_EXE%.
    pause
    exit /b 1
)
set "PYTHON_EXE=%VENV_PYTHON_EXE%"
echo Using Python: %PYTHON_EXE%

"%PYTHON_EXE%" -c "import uvicorn, fastapi, pandas, numpy" >nul 2>&1
if errorlevel 1 (
    echo Installing backend dependencies into .venv...
    "%PYTHON_EXE%" -m pip install -r "%ROOT%backend\requirements.txt"
    if !errorlevel! neq 0 (
        echo ERROR: Failed to install backend dependencies into .venv.
        pause
        exit /b 1
    )
)

echo.
echo === Starting Backend (port 8000) ===
REM 拉满 CPU/IO 并发：解除默认 4/8 的封顶，让真实瓶颈只取决于核心数与各模块 max_limit
set "TRENDZEN_CPU_WORKER_LIMIT=64"
set "TRENDZEN_IO_WORKER_LIMIT=64"
start "Backend" /D "%ROOT%" "%PYTHON_EXE%" -m uvicorn backend.main:app --host 127.0.0.1 --port 8000

echo Waiting for backend to start...
timeout /t 8 /nobreak >nul

REM Check if backend is running
netstat -ano 2>nul | findstr /r "\b:8000\b" >nul
if errorlevel 1 (
    echo WARNING: Backend may not have started. Check the Backend window for errors.
    echo Trying to start backend directly for error output...
    echo.
    "%PYTHON_EXE%" -c "from backend.main import app; print('Import OK')"
    if errorlevel 1 (
        echo.
        echo ERROR: Backend import failed! See errors above.
        pause
        exit /b 1
    )
)

echo.
echo === Starting Frontend (port 5173) ===
cd /d "%ROOT%frontend"
start "Frontend" /D "%ROOT%frontend" npm run dev -- --host 127.0.0.1 --port 5173

echo.
echo === All services started ===
echo Frontend: http://127.0.0.1:5173
echo Backend:  http://127.0.0.1:8000
