# CLAUDE.md — Scribe Dictation

## Project
A cross-platform desktop dictation app. Captures system/microphone audio, sends to OpenAI Whisper for transcription, and pastes the result via a hotkey-driven PySide6 UI.

## Tech stack
- Python 3.12+
- PySide6 — desktop UI
- OpenAI API — Whisper transcription
- sounddevice / soundfile — audio capture
- pyperclip — clipboard paste
- pynput — global hotkeys
- uv — dependency management (uv.lock is committed per policy)

## Layout contract
- `main.py` — app entry point
- `pyproject.toml` — dependencies and project metadata
- `uv.lock` — locked dependencies (committed)
- `.venv/` — local virtual env (gitignored)

## Multi-instance git protocol
Branch per task: `work/<topic>`. Parallel work in this clone → use a git worktree.
Stage only files YOU changed. Never `git add -A` / `git add .` / `commit -a`.
Unexplained dirty/untracked files: leave them, tell the owner.
Before pushing a shared branch: `git pull --rebase`; never force-push.

## Deploy
Desktop app — distributable via PyInstaller or similar. Not configured yet.

## Test / Verify
```bash
# Lint
uv run ruff check .

# Type check
uv run mypy .

# Run app
uv run python main.py
```
