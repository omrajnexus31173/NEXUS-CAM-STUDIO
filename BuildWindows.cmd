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
".venv\Scripts\python.exe" -m pip install -r requirements-dev.txt
if errorlevel 1 goto failed
".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean NexusCamStudio.spec
if errorlevel 1 goto failed
".venv\Scripts\python.exe" -m tools.make_release
if errorlevel 1 goto failed
 echo Built dist\NexusCamStudio.exe and NexusCamStudio-Windows-v1.1.zip
 pause
 exit /b 0
:failed
 echo Build failed. Review the error above. No fake executable was created.
 pause
 exit /b 1
