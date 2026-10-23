@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title GameShelf 0.6 - Bundle Full Emulators
where py >nul 2>&1
if not errorlevel 1 (set "PY=py -3") else (set "PY=python")
%PY% --version >nul 2>&1
if errorlevel 1 (
  echo Python 3.10+ is required to bundle the emulator archives.
  pause
  exit /b 1
)
%PY% BUNDLE_EMULATORS.py
if errorlevel 1 (
  echo Failed to bundle emulator files. See error above. Nothing was removed from the source ZIPs.
  pause
  exit /b 1
)
call INSTALL_AND_RUN.bat
