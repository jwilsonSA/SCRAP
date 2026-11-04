$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectRoot

$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$Python = $VenvPython
if (-not (Test-Path $Python)) {
    $PythonLauncher = Get-Command py -ErrorAction SilentlyContinue
    if ($PythonLauncher) {
        & py -3 -m venv .venv
    } else {
        $SystemPython = Get-Command python -ErrorAction SilentlyContinue
        if (-not $SystemPython) {
            throw "Python is required to build this app. Install Python 3.11-3.13 from python.org and enable Add Python to PATH, or install the Python Launcher."
        }
        & python -m venv .venv
    }
    if (-not (Test-Path $VenvPython)) {
        throw "Failed to create the project virtual environment."
    }
}

& $VenvPython -m pip install --upgrade pip
& $VenvPython -m pip install -r requirements.txt
& $VenvPython -m pip install --upgrade pyinstaller pillow

$IconPng = Join-Path $ProjectRoot "assets\icon.png"
$IconIco = Join-Path $ProjectRoot "assets\icon.ico"

$IconScript = @"
from PIL import Image
image = Image.open(r'''$IconPng''').convert('RGBA')
image.save(r'''$IconIco''', format='ICO', sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)])
"@
& $Python -c $IconScript

& $VenvPython -m PyInstaller --noconfirm --clean SCRAP.spec

$ExePath = Join-Path $ProjectRoot "dist\SCRAP.exe"
if (-not (Test-Path $ExePath)) {
    throw "Build failed: SCRAP.exe was not created."
}

$ReadmePath = Join-Path $ProjectRoot "dist\README.txt"
@"
SCRAP Screen Capture and Recording Platform

1. Extract SCRAP.exe and README.txt from this zip.
2. Run SCRAP.exe. No Python installation or setup is required.

SCRAP.exe is a self-contained portable application. It may create a temporary
runtime folder while starting, then remove it when closed.

Recordings are saved automatically under the current user's Videos folder:
Videos\ScreenRecordings

Windows may show SmartScreen or antivirus warnings for an unsigned app.
"@ | Set-Content -Path $ReadmePath -Encoding ASCII

$PackageFolder = Join-Path $ProjectRoot "dist\SCRAP-Portable"
if (Test-Path $PackageFolder) {
    Remove-Item $PackageFolder -Recurse -Force
}
New-Item -ItemType Directory -Path $PackageFolder | Out-Null
Copy-Item $ExePath -Destination $PackageFolder
Copy-Item $ReadmePath -Destination $PackageFolder

$ZipPath = Join-Path $ProjectRoot "dist\SCRAP-Portable.zip"
if (Test-Path $ZipPath) { Remove-Item $ZipPath -Force }
Start-Sleep -Seconds 2
Compress-Archive -Path (Join-Path $PackageFolder "*") -DestinationPath $ZipPath -CompressionLevel Optimal

Write-Host "Portable app: $ExePath"
Write-Host "Distribution package: $ZipPath"
