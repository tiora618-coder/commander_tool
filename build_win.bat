@echo off
setlocal ENABLEDELAYEDEXPANSION

REM ===============================
REM Paths
REM ===============================
set ROOT_DIR=%~dp0
set RELEASE_DIR=%ROOT_DIR%Release
set DIST_DIR=%ROOT_DIR%dist

set README_BASE=%RELEASE_DIR%\README.txt
set README_TMP=%RELEASE_DIR%\README_release.txt
set README_BAK=%RELEASE_DIR%\README.bak

REM ===============================
REM 1. Get version from main.py
REM ===============================
for /f "tokens=2 delims==" %%A in ('findstr "APP_VERSION" "%ROOT_DIR%main.py"') do (
    set VERSION=%%~A
    set VERSION=!VERSION: =!
    set VERSION=!VERSION:"=!
)

echo === Commander Tool Version: %VERSION% ===


REM ===============================
REM 2. Generate release README (prepend version)
REM ===============================
powershell -NoLogo -NoProfile -Command ^
 "$base=Get-Content -Raw -Encoding UTF8 '%README_BASE%';" ^
 "$header='Commander Tool v%VERSION%' + \"`r`n`r`n\";" ^
 "Set-Content -Encoding UTF8 '%README_TMP%' ($header + $base)"

if errorlevel 1 (
    echo README generation failed.
    exit /b 1
)

echo Release README generated.


REM ===============================
REM 3. Build executable with PyInstaller
REM ===============================
echo Building executable...

pyinstaller ^
 --onefile ^
 --noconsole ^
 --icon "%ROOT_DIR%icons\commander_tool_icon.ico" ^
 --add-data "weights;weights" ^
 --add-data "C:\Users\Lenovo\Documents\MTG\commander_tool\venv\Lib\site-packages\open_clip;open_clip" ^
 --name "CommanderTool" ^
 "%ROOT_DIR%main.py"

if errorlevel 1 (
    echo PyInstaller failed.
    exit /b 1
)

echo Build completed.


REM ===============================
REM 4. Create ZIP (README.txt with version)
REM ===============================
set ZIP_NAME=CommanderTool_v%VERSION%_Win.zip
set ZIP_PATH=%RELEASE_DIR%\%ZIP_NAME%

echo Creating ZIP: %ZIP_NAME%

REM Backup original README.txt
copy /y "%README_BASE%" "%README_BAK%" >nul

REM Replace README.txt with versioned README for ZIP
copy /y "%README_TMP%" "%README_BASE%" >nul

powershell -NoLogo -NoProfile -Command ^
 "Compress-Archive -Force '%DIST_DIR%\CommanderTool.exe','%RELEASE_DIR%\LICENSE','%README_BASE%','%RELEASE_DIR%\Sample_deck_file_Zurgo_Stormrender.txt' '%ZIP_PATH%'"

if errorlevel 1 (
    echo ZIP creation failed.
    REM Restore original README.txt on failure
    copy /y "%README_BAK%" "%README_BASE%" >nul
    del "%README_BAK%" >nul
    del "%README_TMP%" >nul
    exit /b 1
)

REM Restore original README.txt
copy /y "%README_BAK%" "%README_BASE%" >nul

REM Remove temporary files
del "%README_BAK%" >nul
del "%README_TMP%" >nul

echo ZIP created: %ZIP_PATH%


REM ===============================
REM Done
REM ===============================
echo.
echo === Release build finished successfully ===
echo.

pause
