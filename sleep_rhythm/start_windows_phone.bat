@echo off
cd /d "%~dp0"
rem Phone test on the same Wi-Fi: this window shows the address to open on the phone.
where py >nul 2>nul
if %errorlevel%==0 (py -3 run.py --host 0.0.0.0) else (python run.py --host 0.0.0.0)
pause
