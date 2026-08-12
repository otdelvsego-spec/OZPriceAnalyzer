@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    py -3.11 -m venv .venv
    if errorlevel 1 exit /b 1
)
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
if errorlevel 1 exit /b 1
pip install -r requirements-build.txt
if errorlevel 1 exit /b 1

python -m unittest discover -s tests -v
if errorlevel 1 exit /b 1
python scripts\generate_version_info.py
if errorlevel 1 exit /b 1
pyinstaller --noconfirm --clean OZPriceAnalyzer.spec
if errorlevel 1 exit /b 1

powershell -NoProfile -ExecutionPolicy Bypass -File scripts\sign_windows.ps1 ^
  -ExecutablePath dist\OZPriceAnalyzer\OZPriceAnalyzer.exe
if errorlevel 1 exit /b 1
copy /Y README_WINDOWS.txt "dist\OZPriceAnalyzer\Прочтите_перед_запуском.txt" >nul

for /f %%i in ('python -c "from ozon_app import __version__; print(__version__)"') do set APP_VERSION=%%i
if not exist artifacts mkdir artifacts
powershell -NoProfile -Command ^
  "Compress-Archive -Path 'dist\OZPriceAnalyzer\*' -DestinationPath 'artifacts\OZPriceAnalyzer-Windows-x64-v%APP_VERSION%.zip' -Force"
if errorlevel 1 exit /b 1

echo.
echo Готовая программа: dist\OZPriceAnalyzer\OZPriceAnalyzer.exe
echo Архив для передачи: artifacts\OZPriceAnalyzer-Windows-x64-v%APP_VERSION%.zip
