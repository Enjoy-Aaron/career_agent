@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================
echo   Starting Career Growth Agent ...
echo ============================================
python app.py
pause
