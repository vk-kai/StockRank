@echo off
setlocal
echo Stopping port 8000 and 5173...
for /f "tokens=5" %%i in ('netstat -ano ^| findstr /r "\b:8000\b"') do taskkill /F /PID %%i 2>nul
for /f "tokens=5" %%i in ('netstat -ano ^| findstr /r "\b:5173\b"') do taskkill /F /PID %%i 2>nul
echo Done.
