@echo off
rem Build the single-file exe. All logic lives in build_exe.py (Unicode-safe).
rem Prerequisites: pip install nicegui pywebview pyinstaller
rem Close the running exe first (a locked file fails the build).
cd /d "%~dp0"
python build_exe.py
pause
