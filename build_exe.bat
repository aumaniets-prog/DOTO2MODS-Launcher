@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
title D2PFX Launcher - сборка

echo ==============================================
echo   D2PFX Launcher: сборка EXE и установщика
echo ==============================================
echo.

set "PYI_ARGS=--noconfirm --clean --onefile --windowed --name D2PFX_Launcher --icon icon.ico --add-data icon.ico;. --hidden-import PIL._tkinter_finder --collect-submodules PIL launcher.py"

rem ---- 1. Сборка EXE -------------------------------------------------------
where uv >nul 2>nul
if not errorlevel 1 goto build_uv
where py >nul 2>nul
if not errorlevel 1 goto build_py
goto build_python

:build_uv
echo [1/2] Собираю EXE через uv (Python 3.13 + PyInstaller + Pillow)...
uv run --no-project --python 3.13 --with pyinstaller --with pillow pyinstaller %PYI_ARGS%
goto built

:build_py
echo [1/2] Собираю EXE через py ...
py -3 -m pip install --upgrade pyinstaller pillow
py -3 -m PyInstaller %PYI_ARGS%
goto built

:build_python
echo [1/2] Собираю EXE через python ...
python -m pip install --upgrade pyinstaller pillow
python -m PyInstaller %PYI_ARGS%

:built
if not exist "dist\D2PFX_Launcher.exe" (
    echo.
    echo [ОШИБКА] EXE не собрался. Пролистайте вывод выше и пришлите скриншот ошибки.
    pause
    exit /b 1
)
echo.
echo [OK] Готово: dist\D2PFX_Launcher.exe  ^(его можно запускать прямо из папки^)
echo.

rem ---- 2. Установщик (если есть Inno Setup) --------------------------------
set "ISCC="
if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if exist "%LocalAppData%\Programs\Inno Setup 6\ISCC.exe" set "ISCC=%LocalAppData%\Programs\Inno Setup 6\ISCC.exe"

if defined ISCC (
    echo [2/2] Собираю установщик через Inno Setup...
    "%ISCC%" installer.iss
    if exist "installer_output\D2PFX_Launcher_Setup.exe" (
        echo [OK] Установщик: installer_output\D2PFX_Launcher_Setup.exe
    )
) else (
    echo [2/2] Inno Setup не найден - установщик пропущен.
    echo       Если нужен установщик: поставьте Inno Setup 6 ^(jrsoftware.org/isdl.php^)
    echo       или выполните:  winget install JRSoftware.InnoSetup
    echo       и запустите build_exe.bat ещё раз.
)

echo.
explorer "%~dp0dist"
pause
