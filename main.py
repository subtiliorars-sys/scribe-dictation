"""Scribe Dictation - AI-powered speech-to-text desktop app.

Usage:
    python main.py                    # GUI mode
    python main.py --model local      # Use local faster-whisper
    python main.py --model openai     # Use OpenAI Whisper API
"""

import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Configuration / settings
# ---------------------------------------------------------------------------

SETTINGS_FILE = Path.home() / ".scribe-dictation" / "settings.json"
HISTORY_FILE = Path.home() / ".scribe-dictation" / "history.jsonl"
DATA_DIR = Path.home() / ".scribe-dictation"


def _ensure_data_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def load_settings() -> dict:
    defaults: dict = {
        "model": "openai",
        "device": "default",
        "hotkey": "ctrl+shift+d",
        "language": "en",
    }
    try:
        if SETTINGS_FILE.exists():
            with open(SETTINGS_FILE) as f:
                saved = json.load(f)
            defaults.update(saved)
    except (json.JSONDecodeError, OSError):
        pass
    return defaults


def save_settings(settings: dict) -> None:
    _ensure_data_dir()
    with open(SETTINGS_FILE, "w") as f:
        json.dump(settings, f, indent=2)


# ---------------------------------------------------------------------------
# Transcription history
# ---------------------------------------------------------------------------

def save_transcription(text: str, model: str) -> None:
    _ensure_data_dir()
    entry = {"timestamp": datetime.utcnow().isoformat(), "text": text, "model": model}
    with open(HISTORY_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def search_history(query: str) -> list[dict]:
    if not HISTORY_FILE.exists():
        return []
    results = []
    with open(HISTORY_FILE, encoding="utf-8") as f:
        for line in f:
            try:
                entry = json.loads(line)
                if query.lower() in entry.get("text", "").lower():
                    results.append(entry)
            except json.JSONDecodeError:
                continue
    return sorted(results, key=lambda e: e["timestamp"], reverse=True)


# ---------------------------------------------------------------------------
# Model backends
# ---------------------------------------------------------------------------

def transcribe_openai(audio_path: str, settings: dict) -> str:
    import openai
    client = openai.OpenAI()
    with open(audio_path, "rb") as f:
        result = client.audio.transcriptions.create(
            model="whisper-1", file=f, language=settings.get("language", "en"))
    return result.text


def transcribe_local(audio_path: str, settings: dict) -> str:
    from faster_whisper import WhisperModel
    model_size = settings.get("local_model_size", "base")
    model = WhisperModel(model_size, device="cpu", compute_type="int8")
    segments, _ = model.transcribe(audio_path, language=settings.get("language"))
    return " ".join(seg.text for seg in segments)


def transcribe(audio_path: str, settings: Optional[dict] = None) -> str:
    if settings is None:
        settings = load_settings()
    model = settings.get("model", "openai")
    t0 = time.time()
    if model == "local":
        text = transcribe_local(audio_path, settings)
    else:
        text = transcribe_openai(audio_path, settings)
    elapsed_ms = (time.time() - t0) * 1000
    save_transcription(text, model)
    print(f"[{model}] {elapsed_ms:.0f}ms: {text}")
    return text


def show_settings_cli() -> None:
    settings = load_settings()
    print("\n=== Scribe Dictation Settings ===")
    print(f"  1. Model:      {settings['model']}")
    print(f"  2. Device:     {settings['device']}")
    print(f"  3. Hotkey:     {settings['hotkey']}")
    print(f"  4. Language:   {settings['language']}")
    print("================================\n")


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="Scribe Dictation")
    parser.add_argument("--model", choices=["openai", "local"], help="Model backend")
    parser.add_argument("--settings", action="store_true", help="Show settings")
    parser.add_argument("--search", type=str, help="Search dictation history")
    parser.add_argument("file", nargs="?", help="Audio file to transcribe")
    args = parser.parse_args()
    settings = load_settings()
    if args.model:
        settings["model"] = args.model
        save_settings(settings)
    if args.settings:
        show_settings_cli()
        return
    if args.search:
        results = search_history(args.search)
        print(f"\n{len(results)} results for '{args.search}':")
        for r in results[:20]:
            print(f"  [{r['timestamp']}] ({r['model']}): {r['text'][:120]}")
        return
    if args.file:
        text = transcribe(args.file, settings)
        try:
            import pyperclip
            pyperclip.copy(text)
            print("Transcription copied to clipboard.")
        except ImportError:
            pass
        return
    show_settings_cli()


if __name__ == "__main__":
    main()
