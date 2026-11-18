@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist venv ( python -m venv venv )
call venv\Scripts\activate
pip install -q -r requirements.txt
if not exist .env copy .env.example .env >nul
python app.py --headless
pause
