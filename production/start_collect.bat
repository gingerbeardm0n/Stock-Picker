@echo off
cd /d C:\Repositories\Stock-Picker
call .venv\Scripts\activate.bat
python production\data\collector\collect_data.py
