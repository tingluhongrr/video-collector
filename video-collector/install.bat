@echo off
setlocal
cd /d "%~dp0"
"%~dp0..\..\Miniconda\python.exe" -m pip install --upgrade --target "%~dp0.deps" -r requirements.txt
pause
