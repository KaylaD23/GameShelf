@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>&1
if not errorlevel 1 (
  py -3 MIGRATE_FROM_PREVIOUS.py
) else (
  python MIGRATE_FROM_PREVIOUS.py
)
if errorlevel 1 (
  echo Please read the message above. No old files were deleted.
) else (
  echo Migration finished. Launch INSTALL_AND_RUN.bat.
)
pause
