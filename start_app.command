#!/usr/bin/env bash
# Starts the app locally (macOS/Linux). Creates a virtual environment and installs requirements on first run.
cd "$(dirname "$0")"
[ -x .venv/bin/python ] || python3 -m venv .venv
source .venv/bin/activate
python -m pip install -q -r app/requirements.txt
python -m streamlit run app/streamlit_app.py
