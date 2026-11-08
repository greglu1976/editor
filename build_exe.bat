@echo off
chcp 65001 >nul
cd /d "%~dp0"
rem Build the application with the db folder (see PACKAGING.md).
rem   build_exe.bat            - db + exe
rem   build_exe.bat --stage    - only the db folder
rem   build_exe.bat --check    - what is missing
python build_exe.py %*
if errorlevel 1 pause
