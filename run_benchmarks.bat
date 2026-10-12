@echo off
setlocal enabledelayedexpansion

REM ===================================================
REM   Greengold vs C++ vs Rust Benchmark Suite Runner
REM   Usage:
REM     run_benchmarks.bat              (runs all benchmarks)
REM     run_benchmarks.bat fast         (fast mode: 1 iteration)
REM     run_benchmarks.bat primes       (Dave Plummer Drag Race benchmark)
REM     run_benchmarks.bat dragrace     (Plummer Drag Race table and verification)
REM     run_benchmarks.bat fib          (runs only the fib benchmark)
REM     run_benchmarks.bat sieve vector (runs selected benchmarks)
REM     run_benchmarks.bat -n 3         (runs 3 iterations)
REM ===================================================

cd /d "%~dp0"
set "PY=python"
if exist "%~dp0.venv\Scripts\python.exe" set "PY=%~dp0.venv\Scripts\python.exe"

echo ===================================================
echo     Greengold vs C++ vs Rust Benchmark Suite
echo ===================================================

REM 1. Python check
"%PY%" --version >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Python not found! Make sure Python is on your PATH.
    exit /b 1
)

REM 2. Compiler checks
where g++ >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [WARNING] g++ not found. The C++ comparison may not work.
)

where rustc >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [WARNING] rustc not found. The Rust comparison may not work.
)

REM 3. Matplotlib check
"%PY%" -c "import matplotlib" >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [INFO] matplotlib not found. Installing it with pip for the charts...
    "%PY%" -m pip install matplotlib
)

echo.
if "%1"=="dragrace" (
    echo [*] Dave Plummer's Prime Sieve Drag Race...
    "%PY%" "%~dp0benchmarks\drag_race.py"
) else if "%1"=="fast" (
    echo [*] Fast benchmark mode: 1 iteration...
    "%PY%" "%~dp0benchmarks\run_benchmarks.py" -n 1 %2 %3 %4 %5 %6 %7 %8 %9
) else (
    echo [*] Starting benchmarks...
    "%PY%" "%~dp0benchmarks\run_benchmarks.py" %*
)

set BENCH_RESULT=%ERRORLEVEL%

echo.
if %BENCH_RESULT% equ 0 (
    echo ===================================================
    echo   [DONE] Benchmarks finished!
    echo   Charts: in benchmarks\reports\latest\
    echo ===================================================
) else (
    echo ===================================================
    echo   [ERROR] A benchmark failed! (Code: %BENCH_RESULT%)
    echo ===================================================
)

exit /b %BENCH_RESULT%
