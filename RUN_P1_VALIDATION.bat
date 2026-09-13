@echo off
setlocal
cd /d "%~dp0"
py VALIDATION_P1_LIVE.py
exit /b %ERRORLEVEL%
