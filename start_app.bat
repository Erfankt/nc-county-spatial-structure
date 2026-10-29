@echo off
rem Starts the app locally. Creates a virtual environment and installs requirements on first run.
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  py -3 -m venv .venv || python -m venv .venv
)
call ".venv\Scripts\activate.bat"
python -m pip install -q -r app\requirements.txt
python -m streamlit run app\streamlit_app.py
pause
