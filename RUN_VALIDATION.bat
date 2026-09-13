@echo off
REM GUIDED VALIDATION RUNNER FOR RAPHEL
REM Execute this file to capture runtime status and print the manual checklist

set "PROJECT_ROOT=%~dp0"
cd /d "%PROJECT_ROOT%"

echo ========================================
echo RAPHEL GUIDED VALIDATION
echo ========================================
echo.
echo PREPARE IF YOU WANT THE MANUAL DESKTOP CHECKS:
echo  - Browser visible for research verification
echo  - YouTube available for transcript or visible-text checks
echo  - Word or target editor visible for focus verification
echo.
echo Capturing runtime readiness snapshots...
echo.

py "%PROJECT_ROOT%VALIDATION_LIVE_TEST.py"

if %ERRORLEVEL% equ 0 (
    echo.
    echo ========================================
    echo GUIDED VALIDATION COMPLETED
    echo ========================================
) else (
    echo.
    echo ========================================
    echo VALIDATION FAILED - CHECK LOGS
    echo ========================================
)

pause
