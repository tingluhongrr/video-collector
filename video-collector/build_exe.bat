@echo off
setlocal
cd /d "%~dp0"
"%~dp0..\..\Miniconda\python.exe" build_exe.py
pause
