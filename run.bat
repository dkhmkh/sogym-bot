@echo off
echo Installing dependencies...
pip install -r requirements.txt

echo.
echo Starting Sogym Bot...
set /p TOKEN="Enter your Telegram Bot Token: "
set TELEGRAM_BOT_TOKEN=%TOKEN%
python bot.py
pause
