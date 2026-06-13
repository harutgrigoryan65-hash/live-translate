@echo off
cd /d "%~dp0"

if not exist venv (
  py -3 -m venv venv
)

call venv\Scripts\activate.bat
python -c "import google.genai, pyaudio, numpy, soundcard"
if errorlevel 1 (
  python -m pip install -r requirements.txt
)

python app.py
