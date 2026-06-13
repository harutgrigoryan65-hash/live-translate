# Gem Translate

Realtime EN -> target-language translator with an interview assistant, custom answer prompt, and local RAG knowledge base.

## Platform Support

- macOS: microphone, selected window audio, selected app audio.
- Windows: microphone, system output audio through WASAPI loopback via `soundcard`.
- Linux/other: microphone mode only for now.

## Quick Start

The shared cross-platform entry point is:

```bash
python app.py
```

For normal use, prefer the platform launchers below because they create/activate `venv` and install missing dependencies.

### macOS

```zsh
./run_mac_widget.command
```

### Windows

```bat
run_windows.bat
```

Then open `Settings`, paste your Google API key, choose models/languages, and press `Save`.

You can also copy `.env.example` to `.env` and set:

```env
GOOGLE_API_KEY=your_key_here
```

## Manual Setup

Use this when you do not want the launcher scripts:

```bash
python -m venv venv
source venv/bin/activate
python -m pip install -r requirements.txt
python app.py
```

On Windows PowerShell:

```powershell
py -3 -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python app.py
```

## Audio Sources

- `Microphone`: normal input device.
- `Window audio`: macOS only, captures a selected window through ScreenCaptureKit.
- `App audio`: macOS only, captures a selected app through ScreenCaptureKit.
- `System audio`: Windows only, captures the selected output device through loopback.

On macOS, the first window/app capture may require `Screen & System Audio Recording` permission for Terminal/Python.

## Transcript Modes

In `Settings` choose `Transcript mode`:

- `interview`: groups streaming chunks into turns, marks rows `Live`/`Final`, then runs Answer/RAG after the final turn.
- `fast`: immediate stream mode, close to the original fast display.

## Answer Assistant

Enable `Answer` to generate answers for detected questions.

The `Prompt` button opens a custom answer prompt editor. This prompt works with or without RAG, so you can set style and behavior for simple answers:

```text
Answer briefly, from first person, as a candidate in an interview.
Use practical examples when possible. Do not invent personal facts.
```

## Knowledge / RAG

Open `Knowledge` to add `.txt` or `.md` files with resume, projects, portfolio, biography, or prepared answers.

The app stores chunks in `knowledge_base.json` and computes Gemini embeddings for retrieval. RAG controls:

- `RAG`: quick on/off toggle on the main screen.
- `Embedding model`: default `gemini-embedding-2`.
- `Min similarity`: minimum cosine score; below this, RAG is skipped.
- `Top chunks`: max chunks passed to the answer model.

Answers show `RAG used` or `RAG skipped` so you can see whether personal context was used.

## Private Files

Do not commit:

- `settings.json`
- `knowledge_base.json`
- `.env`
- `venv/`
- `window_audio_capture` / `window_audio_capture.exe`

Safe examples are included:

- `settings.example.json`
- `.env.example`

## Project Files

- `app.py`: app entry point.
- `mac_widget.py`: Tkinter UI.
- `translator.py`: audio capture and Gemini Live Translate.
- `answerer.py`: answer model prompt and generation.
- `knowledge_base.py`: local embeddings RAG store.
- `window_audio_capture.swift`: macOS ScreenCaptureKit helper source.
- `run_mac_widget.command`: macOS launcher.
- `run_windows.bat`: Windows launcher.

## Notes

This is an alpha/prototype. Review privacy and API-key handling before using it in real interviews.
