@echo off
setlocal enabledelayedexpansion

REM ===================================================
REM   Greengold Language Test Suite Runner
REM   Usage:
REM     run_tests.bat              (runs the whole test suite)
REM     run_tests.bat fast         (faster: skips the heavy sanitizer/diff tests)
REM     run_tests.bat -v           (verbose pytest output)
REM     run_tests.bat -k <filtre>  (runs selected tests, e.g. -k thread)
REM     run_tests.bat tests/...    (runs one test file)
REM ===================================================

cd /d "%~dp0"
set "PY=python"
if exist "%~dp0.venv\Scripts\python.exe" set "PY=%~dp0.venv\Scripts\python.exe"

echo ===================================================
echo           Greengold Test Runner
echo ===================================================

REM Python check
"%PY%" --version >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Python not found! Make sure Python is on your PATH.
    exit /b 1
)

REM pytest check
"%PY%" -m pytest --version >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [INFO] pytest not found. Installing with pip...
    "%PY%" -m pip install pytest
    if %ERRORLEVEL% neq 0 (
        echo [ERROR] pytest installation failed!
        exit /b 1
    )
)

if "%1"=="fast" (
    echo [*] Running the fast unit tests...
    "%PY%" -m pytest -q --ignore=tests/test_differential.py --ignore=tests/test_sanitize.py %2 %3 %4 %5 %6 %7 %8 %9
) else if "%1"=="" (
    echo [*] Running the whole test suite...
    "%PY%" -m pytest -q
) else (
    echo [*] Running pytest with the parameters: %*
    "%PY%" -m pytest %*
)

set TEST_RESULT=%ERRORLEVEL%

echo.
if %TEST_RESULT% equ 0 (
    echo ===================================================
    echo   [PASSED] All tests passed!
    echo ===================================================
) else (
    echo ===================================================
    echo   [FAILED] Some tests failed! (Exit code: %TEST_RESULT%)
    echo ===================================================
)

exit /b %TEST_RESULT%
