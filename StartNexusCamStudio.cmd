@echo off
setlocal
cd /d "%~dp0"
if not exist "dist\NexusCamStudio.exe" (
  echo The executable is missing. Extract the complete Windows ZIP first.
  echo To run source, use LaunchSource.cmd with Python 3.11 installed.
  pause
  exit /b 1
)
start "Nexus Cam Studio" "%~dp0dist\NexusCamStudio.exe"
