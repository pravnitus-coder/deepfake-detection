@echo off
setlocal
cd /d "%~dp0backend"

where py >nul 2>&1
if errorlevel 1 (
  echo Python 3.10 or newer with the Windows py launcher is required.
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  py -3 -m venv .venv
  if errorlevel 1 goto :error
)

".venv\Scripts\python.exe" -c "import fastapi, uvicorn, multipart, PIL, cv2, soundfile, imageio_ffmpeg, reportlab, dotenv" >nul 2>&1
if errorlevel 1 (
  echo Installing backend dependencies. This may take a few minutes...
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt
  if errorlevel 1 goto :error
)

set "SATYAM_CORS_ORIGINS=http://localhost:5173,null"
echo SATYAM backend is starting at http://localhost:8000
echo Keep this window open while using the app.
".venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
if errorlevel 1 goto :error
exit /b 0

:error
echo.
echo Could not start SATYAM backend. Check the error above.
pause
exit /b 1
