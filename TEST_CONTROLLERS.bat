@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo GameShelf Python environment not found. Run INSTALL_AND_RUN.bat first.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" controller_diagnostics.py --seconds 20
pause
