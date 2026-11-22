@echo off
rem Starts the Kaser games server and opens the launcher in your browser.
rem Leave this window open while you play; close it (or press Ctrl+C) to stop.
rem
rem Games in the usual places (C:\eks, Program Files) are found by themselves.
rem If yours are somewhere else, add the folder at the end of the
rem "server.py" line near the bottom, like this:
rem     --games "D:\Games\Everett Kaser Software"

cd /d "%~dp0"

rem Find a Python that really runs.  Windows has a stand-in "python" that only
rem points to the Microsoft Store, so finding the name isn't enough.
set PY=
py -3 -c "import sys" >nul 2>nul
if not errorlevel 1 (set "PY=py -3" & goto havepython)
python -c "import sys" >nul 2>nul
if not errorlevel 1 (set "PY=python" & goto havepython)
echo.
echo Python isn't installed (Windows only has a shortcut to the Microsoft Store for it).
echo Install it from https://www.python.org/downloads/ and tick
echo "Add python.exe to PATH" during installation, then double-click this file again.
echo.
pause
exit /b 1

:havepython
rem Tablets and phones need a security certificate, which the server makes
rem with the "cryptography" package.  Install it the first time.
%PY% -c "import cryptography" >nul 2>nul
if not errorlevel 1 goto run
echo Installing the "cryptography" package (one time only; needed for tablets and phones)...
%PY% -m pip install --user --disable-pip-version-check --quiet cryptography
if errorlevel 1 echo Couldn't install it.  Games still work on this computer; see README.md.

:run
%PY% server.py --open %*
if errorlevel 1 pause
