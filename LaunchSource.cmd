@echo off
setlocal
cd /d "%~dp0"
py -3.11 --version >nul 2>&1
if errorlevel 1 (
  echo Install Python 3.11 x64 from python.org, including the py launcher.
  pause
  exit /b 1
)
if not exist ".venv\Scripts\python.exe" (
  py -3.11 -m venv .venv
  if errorlevel 1 goto failed
)
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto failed
".venv\Scripts\python.exe" main.py
if errorlevel 1 goto failed
exit /b 0
:failed
 echo Source launch failed. Review the error above and README.md.
 pause
 exit /b 1
