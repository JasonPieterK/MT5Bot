@echo off
echo Installing MT5 Bot...
python -m venv venv
call venv\Scripts\activate.bat
pip install -r requirements.txt
echo Done. Run start.bat to launch.
pause
