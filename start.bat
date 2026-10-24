@echo off
rem RMT - Windows launcher. Double-click it, then open http://localhost:8050
cd /d "%~dp0"

if not exist .venv\Scripts\python.exe (
  echo First run: creating a private Python environment. This takes a minute...
  py -3 -m venv .venv || python -m venv .venv
)
call .venv\Scripts\activate.bat
python -m pip install --quiet --disable-pip-version-check -r requirements.txt

if not exist .env (
  copy .env.example .env >nul
  echo Created a .env file. Open it and paste your Anthropic API key for the AI chat.
)

start "" http://localhost:8050
python -m uvicorn backend.main:app --port 8050
pause
