@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title GameShelf v0.9.12
echo ===================================================
echo      GAMESHELF v0.9.12 - XINPUT + LEGACY CONTROLLERS + BIG PICTURE STATUS
echo ===================================================
if not exist "main.py" (
  echo ERROR: main.py was not found beside this launcher.
  pause
  exit /b 1
)
if exist ".venv\Scripts\python.exe" goto checkdeps
where py >nul 2>&1
if not errorlevel 1 (set "PY=py -3") else (set "PY=python")
%PY% --version >nul 2>&1
if errorlevel 1 (
  echo Python 3.10 or newer is required. Install it and run again.
  pause
  exit /b 1
)
echo Creating local Python environment...
%PY% -m venv ".venv"
if errorlevel 1 goto failed
:checkdeps
".venv\Scripts\python.exe" -c "from version_info import version_file_matches; assert version_file_matches(), 'Version metadata mismatch'"
if errorlevel 1 (
 echo ERROR: GameShelf installation version mismatch.
 pause
 exit /b 1
)
".venv\Scripts\python.exe" -c "import PySide6" >nul 2>&1
if errorlevel 1 (
  echo Installing the PySide6 interface library...
  ".venv\Scripts\python.exe" -m pip install "PySide6>=6.6,<7"
  if errorlevel 1 goto failed
)
rem Existing installations have PySide6 but may lack the new SDL controller support.
".venv\Scripts\python.exe" -c "import pygame; import pygame._sdl2.controller" >nul 2>&1
if errorlevel 1 (
  echo Installing SDL controller support for Xbox, PlayStation and other gamepads...
  ".venv\Scripts\python.exe" -m pip install "pygame-ce>=2.5.3,<3"
  if errorlevel 1 echo WARNING: SDL install failed; XInput controllers may still work.
)
".venv\Scripts\python.exe" -c "import psutil" >nul 2>&1
if errorlevel 1 (
  echo Installing emulator process monitoring support...
  ".venv\Scripts\python.exe" -m pip install "psutil>=5.9,<8"
  if errorlevel 1 goto failed
)
".venv\Scripts\python.exe" main.py
if errorlevel 1 (
 echo GameShelf exited with an error.
 pause
 exit /b 1
)
exit /b 0
:failed
echo Setup failed. Check Python or your internet connection.
pause
exit /b 1
