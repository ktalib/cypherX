@echo off
title CYBEROPS Command Center Launcher
echo [CYBEROPS] Starting Futuristic Command Center...
python main.py
if errorlevel 1 (
    echo [ERROR] Application exited with an error code.
    pause
)
