@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

if not exist "logs" mkdir "logs"
set "PYTHONPATH=%CD%\.deps;%CD%\tools\devshim"

:loop
if exist "logs\stop.flag" goto stopped
if exist ".venv\Scripts\python.exe" goto venv

python -m bot >> "logs\bot.log" 2>&1
goto after

:venv
".venv\Scripts\python.exe" -m bot >> "logs\bot.log" 2>&1

:after
if exist "logs\stop.flag" goto stopped
if errorlevel 2 goto stopped
echo [%DATE% %TIME%] bot stopped, restart in 30s >> "logs\bot.log"

set "WAIT=0"
:wait
if exist "logs\stop.flag" goto stopped
ping -n 2 127.0.0.1 >nul
set /a WAIT+=1
if %WAIT% lss 30 goto wait
goto loop

:stopped
del "logs\stop.flag" >nul 2>&1
exit /b 0
