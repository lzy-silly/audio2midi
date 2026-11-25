@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

rem Prefer a Python interpreter that already has tkinter and basic-pitch.
py -3.11 -c "import tkinter,basic_pitch" >nul 2>nul
if errorlevel 1 goto try311
set "PY=py -3.11"
goto found

:try311
if not exist "C:\Python311\python.exe" goto trylocal
"C:\Python311\python.exe" -c "import tkinter,basic_pitch" >nul 2>nul
if errorlevel 1 goto trylocal
set "PY=C:\Python311\python.exe"
goto found

:trylocal
set "LOCALPY=%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
if not exist "%LOCALPY%" goto trydefault
"%LOCALPY%" -c "import tkinter,basic_pitch" >nul 2>nul
if errorlevel 1 goto trydefault
set "PY=%LOCALPY%"
goto found

:trydefault
python -c "import tkinter,basic_pitch" >nul 2>nul
if errorlevel 1 goto install
set "PY=python"
goto found

:install
echo basic-pitch not found. Installing dependencies, please wait...
python -m pip install -r "%~dp0requirements.txt"
if errorlevel 1 goto fail
set "PY=python"

:found
echo Starting Audio to MIDI Tool...
%PY% "%~dp0audio2midi_gui.py"
if errorlevel 1 pause
exit /b 0

:fail
echo Failed to install dependencies. Please run: python -m pip install -r requirements.txt
pause
exit /b 1
