@echo off
echo Installing...
pip install -r requirements.txt
echo.
echo Starting Sogym App on http://localhost:8000
start http://localhost:8000
python main.py
pause
