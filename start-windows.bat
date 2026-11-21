@echo off
rem Starts the Kaser games server and opens the launcher in your browser.
rem Leave this window open while you play; close it (or press Ctrl+C) to stop.
rem
rem If your games are installed somewhere unusual, add the folder at the end
rem of the "server.py" line below, like this:
rem     --games "D:\Games\Everett Kaser Software"

cd /d "%~dp0"

set PY=
where py >nul 2>nul && set PY=py -3
if not defined PY (
    where python >nul 2>nul && set PY=python
)
if not defined PY (
    echo Python is not installed.  Get it from https://www.python.org/downloads/
    echo and tick "Add python.exe to PATH" during installation, then try again.
    pause
    exit /b 1
)

%PY% server.py --open %*
if errorlevel 1 pause
