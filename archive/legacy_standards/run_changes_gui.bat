@echo off
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
cd /d "%~dp0"

rem Сначала окружение проекта: в нём может быть python-docx.
set "PYEXE="
if exist "%~dp0venv\Scripts\python.exe" set "PYEXE=%~dp0venv\Scripts\python.exe"
if not defined PYEXE if exist "%~dp0.venv\Scripts\python.exe" set "PYEXE=%~dp0.venv\Scripts\python.exe"
if not defined PYEXE if exist "C:\Python313\python.exe" set "PYEXE=C:\Python313\python.exe"

if defined PYEXE (
    "%PYEXE%" changes_gui.py
) else (
    py -3 changes_gui.py
)

if errorlevel 1 (
    echo.
    echo GUI launch failed.
    if defined PYEXE echo   "%PYEXE%" changes_gui.py
    echo Activate the environment and run again:
    echo   venv\Scripts\activate
    echo   python changes_gui.py
    pause
)
