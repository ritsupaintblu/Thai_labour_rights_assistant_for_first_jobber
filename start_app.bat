@echo off
rem Double-click to start the app. The browser opens by itself once the models have loaded (1-2 minutes).
rem Close this window to stop the app.
cd /d "%~dp0"
start "" /b powershell -NoProfile -WindowStyle Hidden -Command "while ($true) { try { Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8000/ -TimeoutSec 2 | Out-Null; break } catch { Start-Sleep 2 } }; Start-Process http://localhost:8000"
echo Loading models, please wait 1-2 minutes. The browser will open by itself.
".venv\Scripts\python.exe" -m uvicorn src.api.main:app --port 8000
pause
