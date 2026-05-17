@echo off
REM Activate virtualenv if present
if exist venv\Scripts\activate.bat (
  call venv\Scripts\activate.bat
)
python weinstein_albert_scanner.py %*
