@echo off
cd /d "%~dp0"
python -m pip install -e . -q 2>nul
python -m patchpipe.cli --lan %*
if errorlevel 1 pause
