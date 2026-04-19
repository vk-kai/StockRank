@echo off
chcp 65001 >nul
title StockRank - Stop Services

echo ========================================
echo    StockRank Dev Server Stopping...
echo ========================================
echo.

echo [1/3] Stopping Backend...
taskkill /fi "windowtitle eq StockRank-Backend*" /f >nul 2>&1

echo [2/3] Stopping Frontend...
taskkill /fi "windowtitle eq StockRank-Frontend*" /f >nul 2>&1

echo [3/3] Stopping Mock News Server...
taskkill /fi "windowtitle eq StockRank-MockNews*" /f >nul 2>&1

echo Cleaning up ports...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":5000 " ^| findstr "LISTENING"') do (
    taskkill /pid %%a /f >nul 2>&1
)
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":5173 " ^| findstr "LISTENING"') do (
    taskkill /pid %%a /f >nul 2>&1
)
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":3000 " ^| findstr "LISTENING"') do (
    taskkill /pid %%a /f >nul 2>&1
)
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8899 " ^| findstr "LISTENING"') do (
    taskkill /pid %%a /f >nul 2>&1
)

echo Clearing logs...
cd /d "%~dp0logs"
if exist error.log (break > error.log) else (type nul > error.log)
if exist data.log (break > data.log) else (type nul > data.log)
if exist system.log (break > system.log) else (type nul > system.log)
for %%f in (*.log.*) do del "%%f" >nul 2>&1
cd ..

echo Clearing news data...
cd /d "%~dp0data\news"
for %%f in (*.json) do del "%%f" >nul 2>&1
cd ..\..

echo.
echo ========================================
echo    All services stopped!
echo    Logs cleared!
echo ========================================
echo.

timeout /t 2 /nobreak >nul
