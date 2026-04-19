@echo off
chcp 65001 >nul
title StockRank Server

echo ========================================
echo    StockRank Server Launcher
echo ========================================
echo.

cd /d "%~dp0"

set /p MODE="Start in DEV mode? (Y/N): "

if /i "%MODE%"=="Y" (
    set STOCKRANK_ENV=dev
    echo.
    echo [Mode: DEV] Using mock news server
) else (
    set STOCKRANK_ENV=prod
    echo.
    echo [Mode: PROD] Using real news API
)

echo.
echo ========================================
echo    Starting Services...
echo ========================================
echo.

if /i "%MODE%"=="Y" (
    echo [1/3] Starting Mock News Server...
    cd test
    start "StockRank-MockNews" cmd /c "python mock_news_server.py"
    cd ..
    timeout /t 2 /nobreak >nul
)

echo [%STOCKRANK_ENV:~0,1%/3] Starting Backend...
cd backend
if /i "%MODE%"=="Y" (
    start "StockRank-Backend" cmd /c "set STOCKRANK_ENV=dev& python app.py"
) else (
    start "StockRank-Backend" cmd /c "set STOCKRANK_ENV=prod& python app.py"
)
cd ..
timeout /t 3 /nobreak >nul

echo [3/3] Starting Frontend...
cd frontend
start "StockRank-Frontend" cmd /c "npm run dev"
cd ..
timeout /t 3 /nobreak >nul

echo.
echo ========================================
echo    All services started!
echo ========================================
echo.
echo  Mode:         %STOCKRANK_ENV%
echo  Backend:      http://localhost:5000
echo  Frontend:     http://localhost:3000
if /i "%MODE%"=="Y" (
echo  Mock News:    http://localhost:8899
)
echo.
echo  Run stop_dev.bat to stop all services
echo ========================================
echo.

start http://localhost:3000

pause
