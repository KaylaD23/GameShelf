@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>&1
if not errorlevel 1 (set "PY=py -3") else (set "PY=python")
%PY% unpack_emulators.py
if errorlevel 1 (
 echo Import unsuccessful. The existing archives and emulator installs have not been modified.
 pause
 exit /b 1
)
echo Emulator files extracted and registered in GameShelf.
pause
