@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title GameShelf v0.9 - Install Citron, shadPS4 and Xenia Canary
where py >nul 2>&1
if not errorlevel 1 (set "PY=py -3") else (set "PY=python")
%PY% BUNDLE_EMULATORS4.py
if errorlevel 1 (
    echo.
    echo Installation failed. Existing emulators and games were not deleted.
    pause
    exit /b 1
)
echo.
echo Emulators 4 verified and integrated. Starting GameShelf...
call INSTALL_AND_RUN.bat
