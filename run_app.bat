@echo off
rem Double-click to start the Deadlock learning helper (needs Python 3.10+ from python.org).
cd /d "%~dp0"
python -m pip install --quiet -r requirements.txt
start "" pythonw -m deadlock_helper
