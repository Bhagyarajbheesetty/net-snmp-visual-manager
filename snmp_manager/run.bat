@echo off
cd /d "%~dp0"
echo Starting SNMP Visual Manager...
echo Open http://127.0.0.1:8080 in your browser
python -m uvicorn main:app --host 127.0.0.1 --port 8080
pause