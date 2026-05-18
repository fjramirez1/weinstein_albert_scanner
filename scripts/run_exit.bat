@echo off
REM Change to project root (parent of this scripts folder)
pushd "%~dp0.."
REM Activate virtualenv if present
if exist venv\Scripts\activate.bat (
  call venv\Scripts\activate.bat
)
python weinstein_albert_exit_scanner.py %*
popd
