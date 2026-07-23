# Signed Windows Build Packaging

## Goal
Ship a signed `.exe` installer for scribe-dictation on Windows.

## Prerequisites
1. **Code signing certificate** — purchase from DigiCert, Sectigo, or SSL.com (~$200-400/yr for OV, ~$80/yr for standard)
2. **PyInstaller** — already in `pyproject.toml`

## Build Steps
```powershell
# 1. One-file build
uv run pyinstaller --onefile --windowed --name "ScribeDictation" src/main.py

# 2. Sign with certificate
signtool sign /fd SHA256 /a /tr http://timestamp.digicert.com /td SHA256 dist/ScribeDictation.exe

# 3. Create installer with NSIS or WiX
makensis installer.nsi
```

## CI Integration
Add to `.github/workflows/ci.yml`:
```yaml
build-windows:
  runs-on: windows-latest
  steps:
    - uses: actions/checkout@v4
    - uses: astral-sh/setup-uv@v5
    - run: uv sync
    - run: uv run pyinstaller --onefile src/main.py
    - uses: actions/upload-artifact@v4
      with:
        name: scribe-dictation-windows
        path: dist/
```

## Current Status
- PyInstaller spec: not yet created
- Certificate: not yet purchased
- CI job: pending implementation
