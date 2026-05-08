@echo off
REM Warehouse Diagnostic Tool Launcher
REM Checks setup steps and activates virtual environment

setlocal enabledelayedexpansion

REM Check if WDT directory exists
if not exist "C:\Users\%USERNAME%\Workspace\WDT" (
    echo.
    echo WDT directory not found. Creating and cloning repository...
    echo.
    mkdir "C:\Users\%USERNAME%\Workspace"
    cd /d "C:\Users\%USERNAME%\Workspace"
    git clone https://github.com/SF-jbs/WDT.git
    if errorlevel 1 (
        echo Error: Failed to clone repository.
        echo Please ensure Git is installed and you have internet access.
        pause
        exit /b 1
    )
)

REM Navigate to the WDT directory using %USERNAME%
cd /d "C:\Users\%USERNAME%\Workspace\WDT"

REM Check if Requirements.txt exists
if not exist "Requirements.txt" (
    echo Error: Requirements.txt not found.
    echo Please ensure you're in the WDT directory.
    pause
    exit /b 1
)

REM Check if virtual environment exists
if not exist ".venv\Scripts\activate.bat" (
    echo.
    echo Virtual environment not found. Creating one now...
    echo.
    python -m venv .venv
    if errorlevel 1 (
        echo Error: Failed to create virtual environment.
        echo Please ensure Python 3.10+ is installed.
        pause
        exit /b 1
    )
)

REM Activate the virtual environment
call .venv\Scripts\activate.bat
if errorlevel 1 (
    echo Error: Failed to activate virtual environment.
    pause
    exit /b 1
)

REM Install/update dependencies
echo.
echo Installing/updating dependencies from Requirements.txt...
echo.
pip install -r Requirements.txt
if errorlevel 1 (
    echo Error: Failed to install dependencies.
    pause
    exit /b 1
)

REM Run the application
echo.
echo Launching Warehouse Diagnostic Tool...
echo.
python warehouse_diagnostics.py

endlocal