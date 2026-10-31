@echo off
rem Builds dist\Togetherogue.exe. Needs Python 3.10 or newer.
cd /d "%~dp0"
python -m pip install -r requirements.txt pyinstaller || goto :failed
python -m PyInstaller --noconfirm --onefile --windowed --name Togetherogue togetherogue.py || goto :failed
echo.
echo Built dist\Togetherogue.exe
pause
exit /b 0

:failed
echo.
echo The build failed.
pause
exit /b 1
