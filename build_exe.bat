@echo off
setlocal
cd /d "%~dp0"

echo ============================================
echo  Building NexusMatchlink.exe
echo ============================================

if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] .venv not found. Create it first.
    exit /b 1
)

echo [1/3] Installing PyInstaller...
".venv\Scripts\python.exe" -m pip install --quiet --upgrade pyinstaller
if errorlevel 1 goto :fail

echo [2/3] Staging clean config template...
rmdir /s /q build_resources 2>nul
mkdir build_resources\config
copy /y config\settings.template.json build_resources\config\settings.json >nul
if errorlevel 1 goto :fail

echo [3/3] Building...
set EXTRA_DATA=
if exist "images\accept_cs2.png" set EXTRA_DATA=--add-data "images\accept_cs2.png;images"
".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean --onefile --windowed ^
    --name "NexusMatchlink" ^
    --icon "assets\icon.ico" ^
    --exclude-module cv2 ^
    --add-data "build_resources\config\settings.json;config" ^
    --add-data "assets\theme_cyberpunk.json;assets" ^
    --add-data "assets\wallpaper.jpg;assets" ^
    --add-data "assets\icon.ico;assets" ^
    --add-data "images\accept.png;images" ^
    %EXTRA_DATA% ^
    --collect-all customtkinter ^
    gui_main.py
if errorlevel 1 goto :fail

rmdir /s /q build_resources 2>nul

echo.
echo ============================================
echo  Done: dist\NexusMatchlink.exe
echo ============================================
pause
exit /b 0

:fail
echo.
echo [ERROR] Build failed.
pause
exit /b 1
