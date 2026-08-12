@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    py -3.11 -m venv .venv
)
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt
pip install pyinstaller
pyinstaller --noconfirm --clean --windowed --name OZPriceAnalyzer ^
  --add-data "ozon_app\resources;ozon_app\resources" main.py
echo.
echo Готовая сборка: dist\OZPriceAnalyzer\OZPriceAnalyzer.exe
