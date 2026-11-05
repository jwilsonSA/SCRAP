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

## Security and false-positive warnings

SCRAP is packaged as a portable Windows executable. Windows SmartScreen or an
antivirus product may initially warn about a newly released or unsigned
application; this is not evidence that a downloaded copy is safe.

Before running:

1. Download only from the official GitHub Releases page, never from a source-code ZIP or mirror.
2. Compare the `SCRAP.exe` SHA-256 hash with `SHA256SUMS.txt` in the portable package.
3. Do not use "Run anyway"/allow-list overrides unless the hash matches the official release.

SCRAP does not install browser extensions, and recordings are saved only to the
current user's Videos\ScreenRecordings folder.

## Build

Windows PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File .\build_portable.ps1
```
