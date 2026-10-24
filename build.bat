@echo off
REM ============================================================
REM  Flow Image Manager — PyInstaller Build Script
REM  Packages the application as a standalone Windows executable.
REM ============================================================

cd /d "%~dp0"

echo Checking PyInstaller...
python -m PyInstaller --version >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo Installing PyInstaller...
    pip install pyinstaller
)

echo Building Flow Image Manager standalone executable...
python -m PyInstaller ^
    --name "FlowImageManager" ^
    --onefile ^
    --windowed ^
    --clean ^
    --icon "assets/icon.ico" ^
    --add-data "config;config" ^
    --add-data "assets;assets" ^
    --add-data "app;app" ^
    --hidden-import "PySide6.QtCore" ^
    --hidden-import "PySide6.QtGui" ^
    --hidden-import "PySide6.QtWidgets" ^
    --hidden-import "PySide6.QtSvg" ^
    --hidden-import "cv2" ^
    --hidden-import "PIL" ^
    main.py

if %ERRORLEVEL% equ 0 (
    echo.
    echo ============================================================
    echo Build complete! Executable: dist\FlowImageManager.exe
    echo ============================================================
) else (
    echo.
    echo Build FAILED. Check output above.
)
pause
