@echo off
chcp 65001 >nul
cd /d "%~dp0"

if not exist "logs" mkdir "logs"
echo stop > "logs\stop.flag"

taskkill /F /IM python3.13.exe >nul 2>&1
taskkill /F /IM python.exe >nul 2>&1

echo.
echo Bot stopped.
timeout /t 3 /nobreak >nul
del "logs\stop.flag" >nul 2>&1
pause
