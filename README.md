# SCRAP

SCRAP is a Windows screen capture and recording application.

## Download

Use the portable Windows release:

https://github.com/jwilsonSA/SCRAP/releases/latest

Do not run `SCRAP.exe` from a downloaded source-code ZIP. The source ZIP is for
development, and files under `build/` or `dist/` are generated build artifacts.

## Run

1. Download `SCRAP-Portable.zip` from the latest release.
2. Extract the complete ZIP.
3. Run the extracted `SCRAP.exe`.

Python is not required.

## Build

Windows PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File .\build_portable.ps1
```
