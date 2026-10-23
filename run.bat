@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

set "PYTHONPATH=%CD%\.deps;%CD%\tools\devshim"

if not exist ".env" goto no_env
if exist ".venv\Scripts\python.exe" goto use_venv

python -m bot
goto done

:use_venv
".venv\Scripts\python.exe" -m bot
goto done

:no_env
echo.
echo .env not found in this folder.
echo Copy .env.example to .env and put your BOT_TOKEN there.
echo.

:done
echo.
echo Bot stopped.
pause
