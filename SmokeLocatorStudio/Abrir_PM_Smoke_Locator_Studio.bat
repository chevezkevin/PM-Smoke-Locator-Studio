@echo off
setlocal
cd /d "%~dp0"
python smoke_locator_studio.py
if errorlevel 1 pause
