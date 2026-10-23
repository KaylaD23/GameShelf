@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>&1
if not errorlevel 1 (set "PY=py -3") else (set "PY=python")
if not exist ".venv\Scripts\python.exe" (
 %PY% -m venv .venv
 if errorlevel 1 goto :fail
)
".venv\Scripts\python.exe" -m pip install -r requirements.txt pyinstaller
if errorlevel 1 goto :fail
".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean --windowed --onedir --hidden-import cover_ui --hidden-import cover_downloader --name GameShelf main.py
if errorlevel 1 goto :fail
if exist "Emulators\" (
 echo Copying the bundled emulators into the executable distribution...
 robocopy "Emulators" "dist\GameShelf\Emulators" /E /R:2 /W:1 /NFL /NDL /NJH /NJS
 if errorlevel 8 goto :fail
)
echo Finished: dist\GameShelf\GameShelf.exe (emulators included)
pause
exit /b 0
:fail
echo Build failed. See messages above.
pause
exit /b 1
