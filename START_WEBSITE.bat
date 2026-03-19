@echo off
title Secure Property Hub V2
color 0A
echo.
echo  ==========================================
echo   SECURE PROPERTY HUB V2 - Starting...
echo  ==========================================
echo.
cd /d "%~dp0"
start "" "http://localhost:5000"
python app.py
pause
