@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ============================================
echo   局域网演示模式（同一 WiFi 下他人可访问）
echo ============================================
echo.

echo [1/2] 设置 Ollama 对外监听（供本机模型服务被访问）...
set OLLAMA_HOST=0.0.0.0

echo [2/2] 启动服务并绑定局域网...
echo.
set CAREER_HOST=0.0.0.0
python app.py

pause
