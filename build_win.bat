@echo off
setlocal ENABLEDELAYEDEXPANSION

REM ===============================
REM Paths
REM ===============================
set ROOT_DIR=%~dp0
set RELEASE_DIR=%ROOT_DIR%Release
set DIST_DIR=%ROOT_DIR%dist
set MAIN_FILE=%ROOT_DIR%main.py
set MAIN_FILE_BAK=%ROOT_DIR%main.bak

set README_BASE=%RELEASE_DIR%\README.txt
set README_TMP=%RELEASE_DIR%\README_release.txt
set README_BAK=%RELEASE_DIR%\README.bak

REM ===============================
REM Find open_clip folder dynamically
REM ===============================
for /d %%D in ("%ROOT_DIR%venv\Lib\site-packages\open_clip") do (
    set OPEN_CLIP_PATH=%%D
)

if not exist "%OPEN_CLIP_PATH%" (
    echo ERROR: open_clip not found in venv!
    exit /b 1
)

echo Found open_clip: %OPEN_CLIP_PATH%


REM ===============================
REM Disable DEBUG_LOG in main.py
REM ===============================
echo Backing up main.py and disabling DEBUG_LOG...

copy /y "%MAIN_FILE%" "%MAIN_FILE_BAK%" >nul

powershell -NoLogo -NoProfile -Command ^
 "$text = Get-Content '%MAIN_FILE%' -Raw -Encoding UTF8;" ^
 "$text = $text -replace 'DEBUG_LOG *= *True','DEBUG_LOG = False';" ^
 "Set-Content -Encoding UTF8 '%MAIN_FILE%' $text"

if errorlevel 1 (
    echo Failed to update DEBUG_LOG in main.py
    exit /b 1
)

echo DEBUG_LOG disabled.


REM ===============================
REM 1. Get version from config.py
REM ===============================
for /f "tokens=2 delims==" %%A in ('findstr "APP_VERSION" "%ROOT_DIR%config.py"') do (
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
 --add-data "%ROOT_DIR%icons;icons" ^
 --add-data "%OPEN_CLIP_PATH%;open_clip" ^
 --name "CommanderTool" ^
 "%MAIN_FILE%"

if errorlevel 1 (
    echo PyInstaller failed.
    goto RESTORE_MAIN
)

echo Build completed.


REM ===============================
REM 4. Create ZIP
REM ===============================
set ZIP_NAME=CommanderTool_v%VERSION%_Win.zip
set ZIP_PATH=%RELEASE_DIR%\%ZIP_NAME%

echo Creating ZIP: %ZIP_NAME%

copy /y "%README_BASE%" "%README_BAK%" >nul
copy /y "%README_TMP%" "%README_BASE%" >nul

powershell -NoLogo -NoProfile -Command ^
 "Compress-Archive -Force '%DIST_DIR%\CommanderTool.exe','%RELEASE_DIR%\LICENSE','%README_BASE%','%RELEASE_DIR%\Sample_deck_file_Zurgo_Stormrender.txt' '%ZIP_PATH%'"

copy /y "%README_BAK%" "%README_BASE%" >nul
del "%README_BAK%" >nul
del "%README_TMP%" >nul

echo ZIP created: %ZIP_PATH%


REM ===============================
REM Restore original main.py
REM ===============================
:RESTORE_MAIN
echo Restoring original main.py...
copy /y "%MAIN_FILE_BAK%" "%MAIN_FILE%" >nul
del "%MAIN_FILE_BAK%" >nul

echo main.py restored.

echo.
echo === Release build finished successfully ===
echo.
pause
