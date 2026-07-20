# Changelog

## 2026-07-15

### Added
- Global hotkey (Ctrl+Shift+D), auto-paste, and system tray (#88cec80, #92589ee)
- Property/fuzz tests for WAV header parsing (#7)

### Fixed
- Resolved pre-existing ruff lint errors blocking CI (#b80fec9)
- CI: added ruff as dev dependency for `uv run ruff check` (#715b9fb)

### Docs
- Added START_HERE.md routing back to neural-network hub (#d8f869b)
- Added multi-agent coordination section with kanban reference (#1938f49)

---

## 2026-07-14

### Added
- Initial project scaffold (#72ad444)
- Audio capture module — start/stop/pause/resume with silence detection (#0216f6e)
- Transcription service with OpenAI Whisper API integration (#cabface)
- Core dictation application (PySide6 desktop app) (#514f467, #e6537af)

### Setup
- Added CLAUDE.md and GitHub templates (#04ed02c)

---

## Open (2026-07-20)

See [GitHub Issues](https://github.com/subtiliorars-sys/scribe-dictation/issues) — 8 open feature requests including:
- Whisper model selection + local model support (faster-whisper)
- Settings UI (device, model, hotkey)
- Dictation history + search
- Clipboard auto-paste of transcription result
- Export transcriptions to .txt/.md/.srt
- Signed Windows build (PyInstaller)
- Integration tests (capture → transcribe → clipboard)
- Pre-commit hooks (format + secret scan)
