@echo off
setlocal

title Med Connect Server
cd /d "%~dp0"

echo.
echo Starting Med Connect with the existing command: python app.py
echo WAMP MySQL should be running on 127.0.0.1:3306.
echo Keep this window open to monitor server logs and errors.
echo.

start "Med Connect Browser" http://localhost:5000
python app.py

echo.
echo Med Connect server stopped with exit code %errorlevel%.
pause
endlocal