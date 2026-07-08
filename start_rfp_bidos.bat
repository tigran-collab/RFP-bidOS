@echo off
title RFP BidOS Launcher

echo Starting RFP BidOS backend...
start "RFP BidOS Backend" cmd /k "cd /d %~dp0backend && .venv\Scripts\activate.bat && uvicorn app.main:app --reload"

echo Starting RFP BidOS frontend...
start "RFP BidOS Frontend" cmd /k "cd /d %~dp0frontend && npm.cmd run dev"

echo Waiting for app to start...
timeout /t 8 /nobreak >nul

echo Opening RFP BidOS in browser...
start http://localhost:5173

REM Note: this launcher does not start Ollama. Start it separately (ollama serve)
REM if you need local AI features. The Electron launcher and the mac script do
REM start Ollama automatically.

exit
