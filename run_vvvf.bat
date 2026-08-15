@echo off
setlocal

cd /d "%~dp0"
set "VVVF_PYTHON=%~dp0.venv\Scripts\python.exe"

if not exist "%VVVF_PYTHON%" (
    echo [ERROR] Local Python environment was not found:
    echo         %VVVF_PYTHON%
    echo.
    echo Recreate .venv and install requirements before running.
    pause
    exit /b 1
)

"%VVVF_PYTHON%" "%~dp0main.py" %*
set "VVVF_EXIT_CODE=%ERRORLEVEL%"

if not "%VVVF_EXIT_CODE%"=="0" (
    echo.
    echo [ERROR] VVVF Simulator exited with code %VVVF_EXIT_CODE%.
    pause
)

endlocal & exit /b %VVVF_EXIT_CODE%
