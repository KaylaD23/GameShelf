@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>&1
if not errorlevel 1 (set "PY=py -3") else (set "PY=python")
%PY% verify_bundled.py --deep
if errorlevel 1 (echo One or more files are missing or damaged.) else (echo All bundled emulator files passed verification.)
pause
