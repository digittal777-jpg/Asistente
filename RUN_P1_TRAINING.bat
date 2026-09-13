@echo off
setlocal EnableExtensions
set "PROJECT_ROOT=%~dp0"
cd /d "%PROJECT_ROOT%"

set "PYTHON_EXE=%PROJECT_ROOT%.venv\Scripts\python.exe"
set "ARGS=--supervised"
if not "%~1"=="" set "ARGS=%*"

set "ITERATION=1"

echo ========================================
echo RAPHEL P1 SUPERVISED TRAINING LOOP
echo ========================================
echo.
echo Este archivo ejecuta VALIDATION_P1_LIVE.py varias veces
echo para que el sistema practique y registre evidencia.
echo Presiona Ctrl+C para detenerlo.
echo.

:loop
echo === Iteracion %ITERATION% ===
echo Inicio: %date% %time%
if exist "%PYTHON_EXE%" (
    "%PYTHON_EXE%" "%PROJECT_ROOT%VALIDATION_P1_LIVE.py" %ARGS%
) else (
    py "%PROJECT_ROOT%VALIDATION_P1_LIVE.py" %ARGS%
)

echo.
echo Esperando 10 minutos antes de la siguiente ronda...
ping 127.0.0.1 -n 601 >nul
set /a ITERATION+=1
goto loop
