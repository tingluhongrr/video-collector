@echo off
setlocal
cd /d "%~dp0"
"%~dp0..\..\Miniconda\python.exe" gui.py
if errorlevel 1 pause
