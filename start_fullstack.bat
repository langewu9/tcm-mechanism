@echo off
cd /d "%~dp0"

echo Starting Qihuang full-stack services...
echo.
echo 1. Next.js: http://127.0.0.1:3000
echo 2. FastAPI: http://127.0.0.1:8010
echo 3. BianCang OpenAI API: http://127.0.0.1:8000/v1
echo 4. API Integration Console: http://127.0.0.1:3000/api-integration
echo.

start "qihuang-next" cmd /k "cd /d %~dp0 && npm --cache .\.npm-cache run dev"
start "qihuang-fastapi" cmd /k "cd /d %~dp0 && D:\mini\envs\py310\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8010"
start "qihuang-biancang" cmd /k "cd /d %~dp0 && set BIANCANG_MAX_NEW_TOKENS=256 && D:\mini\envs\py310\python.exe tools\serve_biancang_openai.py --host 127.0.0.1 --port 8000"

echo Services are launching in separate windows. Keep those windows open while using the platform.
pause
