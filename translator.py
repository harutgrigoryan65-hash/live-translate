import asyncio
import json
import os
import platform
import struct
import subprocess
import threading
from typing import Callable

from google import genai
from google.genai import types
import pyaudio

AUDIO_SAMPLE_RATE = 16000
CHUNK_SIZE = 1600
AUDIO_FORMAT = pyaudio.paInt16
CHANNELS = 1
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
WINDOW_AUDIO_SOURCE = os.path.join(BASE_DIR, "window_audio_capture.swift")
WINDOW_AUDIO_HELPER = os.path.join(BASE_DIR, "window_audio_capture")
IS_MACOS = platform.system() == "Darwin"
IS_WINDOWS = platform.system() == "Windows"


def rms(data):
    samples = struct.unpack(f"{len(data)//2}h", data)
    return (sum(s * s for s in samples) / len(samples)) ** 0.5


def list_input_devices():
    audio = pyaudio.PyAudio()
    devices = []
    try:
        try:
            default_index = audio.get_default_input_device_info()["index"]
        except Exception:
            default_index = None

        for i in range(audio.get_device_count()):
            info = audio.get_device_info_by_index(i)
            if info["maxInputChannels"] > 0:
                devices.append(
                    {
                        "index": i,
                        "name": info["name"],
                        "is_default": i == default_index,
                    }
                )
    finally:
        audio.terminate()
    return devices


def build_window_audio_helper():
    if not IS_MACOS:
        raise RuntimeError("Window/App audio доступен только на macOS через ScreenCaptureKit.")
    if not os.path.exists(WINDOW_AUDIO_SOURCE):
        raise RuntimeError("window_audio_capture.swift не найден.")

    helper_missing = not os.path.exists(WINDOW_AUDIO_HELPER)
    helper_stale = helper_missing or (
        os.path.getmtime(WINDOW_AUDIO_SOURCE) > os.path.getmtime(WINDOW_AUDIO_HELPER)
    )
    if not helper_stale:
        return

    command = [
        "xcrun",
        "swiftc",
        "-parse-as-library",
        "-O",
        "-framework",
        "ScreenCaptureKit",
        "-framework",
        "AVFoundation",
        "-framework",
        "CoreMedia",
        WINDOW_AUDIO_SOURCE,
        "-o",
        WINDOW_AUDIO_HELPER,
    ]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(
            "Не удалось собрать helper для захвата окна:\n"
            + (result.stderr.strip() or result.stdout.strip())
        )


def list_audio_windows():
    if not IS_MACOS:
        raise RuntimeError("Window audio доступен только на macOS.")
    build_window_audio_helper()
    result = subprocess.run(
        [WINDOW_AUDIO_HELPER, "list"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            "Не удалось получить список окон:\n"
            + (result.stderr.strip() or result.stdout.strip())
        )
    return json.loads(result.stdout or "[]")


def list_audio_apps():
    if not IS_MACOS:
        raise RuntimeError("App audio доступен только на macOS.")
    build_window_audio_helper()
    result = subprocess.run(
        [WINDOW_AUDIO_HELPER, "list-apps"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            "Не удалось получить список приложений:\n"
            + (result.stderr.strip() or result.stdout.strip())
        )
    return json.loads(result.stdout or "[]")


def list_system_audio_devices():
    if not IS_WINDOWS:
        return []
    try:
        import soundcard as sc
    except ImportError as exc:
        raise RuntimeError(
            "Для System audio на Windows установи dependency: pip install soundcard numpy"
        ) from exc

    try:
        default = sc.default_speaker()
        default_id = default.id
    except Exception:
        default_id = None

    devices = []
    for speaker in sc.all_speakers():
        devices.append(
            {
                "id": speaker.id,
                "name": speaker.name,
                "is_default": speaker.id == default_id,
            }
        )
    return devices


def choose_device():
    devices = list_input_devices()
    print("Доступные микрофоны:")
    for device in devices:
        default_mark = " <-- по умолчанию" if device["is_default"] else ""
        print(f"  [{device['index']}] {device['name']}{default_mark}")

    choice = input("\nВведи номер устройства (Enter = по умолчанию): ").strip()
    if choice == "":
        return None  # None = системный default
    return int(choice)


def _call(callback, *args):
    if callback:
        callback(*args)


async def capture_and_translate(
    device_index=None,
    source_type: str = "microphone",
    window_id: int | None = None,
    app_pid: int | None = None,
    system_audio_id: str | None = None,
    api_key: str | None = None,
    model: str = "gemini-3.5-live-translate-preview",
    target_language_code: str = "ru",
    echo_target_language: bool = False,
    on_input: Callable[[str], None] | None = None,
    on_output: Callable[[str], None] | None = None,
    on_level: Callable[[float], None] | None = None,
    on_status: Callable[[str], None] | None = None,
    should_stop: Callable[[], bool] | None = None,
):
    api_key = api_key or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError("GOOGLE_API_KEY не задан. Добавь ключ в переменные окружения.")

    client = genai.Client(api_key=api_key)
    config = types.LiveConnectConfig(
        response_modalities=["AUDIO"],
        input_audio_transcription=types.AudioTranscriptionConfig(),
        output_audio_transcription=types.AudioTranscriptionConfig(),
        translation_config=types.TranslationConfig(
            target_language_code=target_language_code,
            echo_target_language=echo_target_language,
        ),
    )

    audio = None
    stream = None
    window_process = None
    window_stderr = []
    stderr_thread = None
    system_recorder_cm = None
    system_recorder = None
    try:
        if source_type in ("window", "app"):
            if source_type == "window" and window_id is None:
                raise RuntimeError("Выбери окно для захвата аудио.")
            if source_type == "app" and app_pid is None:
                raise RuntimeError("Выбери приложение для захвата аудио.")
            build_window_audio_helper()
            helper_args = (
                ["capture-window", str(window_id)]
                if source_type == "window"
                else ["capture-app", str(app_pid)]
            )
            window_process = subprocess.Popen(
                [WINDOW_AUDIO_HELPER, *helper_args],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            def drain_stderr():
                if not window_process or not window_process.stderr:
                    return
                for raw_line in iter(window_process.stderr.readline, b""):
                    line = raw_line.decode("utf-8", errors="replace").strip()
                    if line:
                        window_stderr.append(line)

            stderr_thread = threading.Thread(target=drain_stderr, daemon=True)
            stderr_thread.start()
            _call(on_status, "opening_window" if source_type == "window" else "opening_app")
        elif source_type == "system_audio":
            if not IS_WINDOWS:
                raise RuntimeError("System audio сейчас доступен только на Windows.")
            try:
                import numpy as np
                import soundcard as sc
            except ImportError as exc:
                raise RuntimeError(
                    "Для System audio на Windows установи dependency: pip install soundcard numpy"
                ) from exc
            speaker = sc.get_speaker(system_audio_id) if system_audio_id else sc.default_speaker()
            system_recorder_cm = speaker.recorder(
                samplerate=AUDIO_SAMPLE_RATE,
                channels=CHANNELS,
            )
            system_recorder = system_recorder_cm.__enter__()
            _call(on_status, "opening_system_audio")
        else:
            audio = pyaudio.PyAudio()
            stream = audio.open(
                format=AUDIO_FORMAT,
                channels=CHANNELS,
                rate=AUDIO_SAMPLE_RATE,
                input=True,
                input_device_index=device_index,
                frames_per_buffer=CHUNK_SIZE,
            )

        _call(on_status, "listening")

        loop = asyncio.get_event_loop()
        should_stop = should_stop or (lambda: False)

        def read_chunk():
            if source_type in ("window", "app"):
                if not window_process or not window_process.stdout:
                    raise RuntimeError("Helper захвата аудио не запущен.")
                data = window_process.stdout.read(CHUNK_SIZE * 2)
                if len(data) < CHUNK_SIZE * 2:
                    details = "\n".join(window_stderr[-5:])
                    raise RuntimeError(
                        "Захват аудио остановился."
                        + (f"\n{details}" if details else "")
                    )
                return data
            if source_type == "system_audio":
                frames = system_recorder.record(numframes=CHUNK_SIZE)
                if frames.ndim > 1:
                    frames = frames[:, 0]
                samples = np.clip(frames, -1.0, 1.0)
                return (samples * 32767).astype("<i2").tobytes()
            return stream.read(CHUNK_SIZE, exception_on_overflow=False)

        async with client.aio.live.connect(model=model, config=config) as session:
            _call(on_status, "connected")

            chunks_sent = 0

            async def send_audio():
                nonlocal chunks_sent
                try:
                    while not should_stop():
                        data = await loop.run_in_executor(None, read_chunk)
                        level = rms(data)
                        chunks_sent += 1
                        _call(on_level, level)
                        if chunks_sent % 20 == 0:
                            bar = "#" * int(level / 200)
                            print(f"  [mic: {level:6.0f}] {bar}", flush=True)
                        await session.send_realtime_input(
                            audio=types.Blob(
                                data=data,
                                mime_type="audio/pcm;rate=16000",
                            )
                        )
                except asyncio.CancelledError:
                    pass

            async def receive_translations():
                async for response in session.receive():
                    if should_stop():
                        break

                    content = getattr(response, "server_content", None) or response
                    input_transcription = getattr(content, "input_transcription", None)
                    output_transcription = getattr(content, "output_transcription", None)

                    if input_transcription:
                        text = getattr(input_transcription, "text", None)
                        if text:
                            _call(on_input, text)
                    if output_transcription:
                        text = getattr(output_transcription, "text", None)
                        if text:
                            _call(on_output, text)

            send_task = asyncio.create_task(send_audio())
            receive_task = asyncio.create_task(receive_translations())

            try:
                while not should_stop() and not receive_task.done():
                    await asyncio.sleep(0.1)
            finally:
                for task in (send_task, receive_task):
                    task.cancel()
                for task in (send_task, receive_task):
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass

    except KeyboardInterrupt:
        print("\nПеревод остановлен")
    except asyncio.CancelledError:
        _call(on_status, "stopped")
    except Exception as e:
        _call(on_status, "error")
        print(f"Ошибка: {e}")
        raise
    finally:
        _call(on_status, "stopped")
        if window_process:
            window_process.terminate()
            try:
                window_process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                window_process.kill()
        if stream:
            stream.stop_stream()
            stream.close()
        if audio:
            audio.terminate()
        if system_recorder_cm:
            system_recorder_cm.__exit__(None, None, None)


async def capture_and_print(device_index):
    print("\nГовори по-английски. Нажми Ctrl+C для остановки.\n")

    def print_input(text):
        print(f"\nАнглийский: {text}")

    def print_output(text):
        print(f"Русский:    {text}\n")

    await capture_and_translate(
        device_index=device_index,
        on_input=print_input,
        on_output=print_output,
    )


if __name__ == "__main__":
    idx = choose_device()
    asyncio.run(capture_and_print(idx))
