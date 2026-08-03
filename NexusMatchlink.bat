@echo off
setlocal
cd /d "%~dp0"
title Nexus Matchlink

if not exist ".venv\Scripts\pythonw.exe" (
    echo [!] Виртуальное окружение не найдено.
    echo.
    echo     Первый запуск:
    echo       python -m venv .venv
    echo       .venv\Scripts\pip install -r requirements.txt
    echo.
    echo     Затем запустите этот файл снова.
    echo.
    pause
    exit /b 1
)

start "" ".venv\Scripts\pythonw.exe" gui_main.py
