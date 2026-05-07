@echo off
setlocal enabledelayedexpansion

:: 1. Set Path Variables
set "ROOT_DIR=%~dp0"
set "APP_DIR=%ROOT_DIR%electron-app"
set "DIST_DIR=%APP_DIR%\dist"
set "STATIC_LINK=%APP_DIR%\static"
set "SOURCE_STATIC=%ROOT_DIR%static"

echo [1/5] Cleaning old builds and links...
if exist "%DIST_DIR%" (
    echo Deleting %DIST_DIR%...
    rmdir /s /q "%DIST_DIR%"
)

if exist "%STATIC_LINK%" (
    echo Deleting old link %STATIC_LINK%...
    if exist "%STATIC_LINK%\" (
        rmdir /s /q "%STATIC_LINK%"
    ) else (
        del /f /q "%STATIC_LINK%"
    )
)

echo.
echo [2/5] Creating static Junction...
pushd "%APP_DIR%"
if not exist "static" (
    mklink /j "static" "%SOURCE_STATIC%"
)
popd

echo.
echo [3/5] Installing NPM dependencies...
pushd "%APP_DIR%"
call npm install
if %errorlevel% neq 0 (
    echo Error: NPM Install failed!
    popd
    pause
    exit /b %errorlevel%
)
popd

echo.
echo [4/5] Running Electron Build...
pushd "%APP_DIR%"
call npm run build
if %errorlevel% neq 0 (
    echo Error: Build failed!
    popd
    pause
    exit /b %errorlevel%
)
popd

echo.
echo [5/5] Done!
echo Output: %DIST_DIR%
pause