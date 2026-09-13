@echo off
setlocal
cd /d "%~dp0"
py RAPHEL_DOCTOR.py
exit /b %ERRORLEVEL%
