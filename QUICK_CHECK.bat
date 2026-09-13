@echo off
REM QUICK VALIDATION CHECK - Code Integrity Verification
REM This script verifies that all the fixes are in place

set "PROJECT_ROOT=%~dp0"
cd /d "%PROJECT_ROOT%"

echo.
echo ========================================
echo RAPHEL - QUICK VALIDATION CHECK
echo ========================================
echo.
echo Checking code integrity of fixes...
echo.

py "%PROJECT_ROOT%QUICK_VALIDATION_CHECK.py"

if %ERRORLEVEL% equ 0 (
    echo.
    echo ========================================
    echo CODE CHECKS PASSED!
    echo ========================================
    echo.
echo Next steps:
echo 1. If you want a live desktop pass, prepare browser and editor windows
echo 2. Run: RUN_VALIDATION.bat
    echo.
) else (
    echo.
    echo ========================================
    echo SOME CHECKS FAILED
    echo ========================================
)

pause
