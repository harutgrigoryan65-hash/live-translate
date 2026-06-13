#!/bin/zsh
cd "$(dirname "$0")"

if [ ! -d "venv" ]; then
  python3 -m venv venv
fi

source venv/bin/activate
python - <<'PY' || python -m pip install -r requirements.txt
import google.genai
import pyaudio
PY
python app.py
