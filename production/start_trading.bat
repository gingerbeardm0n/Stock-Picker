@echo off
cd /d C:\Repositories\Stock-Picker
call .venv\Scripts\activate.bat
python production\run_trading.py
