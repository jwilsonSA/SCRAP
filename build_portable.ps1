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

$ExePath = Join-Path $ProjectRoot "dist\SCRAP\SCRAP.exe"
if (-not (Test-Path $ExePath)) {
    throw "Build failed: SCRAP.exe was not created."
}

$ReadmePath = Join-Path $ProjectRoot "dist\SCRAP\README.txt"
@"
SCRAP Screen Capture and Recording Platform

1. Extract this entire SCRAP folder.
2. Keep SCRAP.exe and the _internal folder together.
3. Run SCRAP.exe.

Recordings are saved automatically under the current user's Videos folder:
Videos\ScreenRecordings

Windows may show SmartScreen or antivirus warnings for an unsigned app.
"@ | Set-Content -Path $ReadmePath -Encoding ASCII

$ZipPath = Join-Path $ProjectRoot "dist\SCRAP-Portable.zip"
if (Test-Path $ZipPath) { Remove-Item $ZipPath -Force }
Add-Type -AssemblyName System.IO.Compression.FileSystem
$PortableFolder = Join-Path $ProjectRoot "dist\SCRAP"
[IO.Compression.ZipFile]::CreateFromDirectory(
    $PortableFolder,
    $ZipPath,
    [IO.Compression.CompressionLevel]::Optimal,
    $false
)

$DesktopPath = [Environment]::GetFolderPath("Desktop")
$ShortcutPath = Join-Path $DesktopPath "SCRAP.lnk"
$Shell = New-Object -ComObject WScript.Shell
$Shortcut = $Shell.CreateShortcut($ShortcutPath)
$Shortcut.TargetPath = $ExePath
$Shortcut.WorkingDirectory = Split-Path -Parent $ExePath
$Shortcut.IconLocation = $IconIco
$Shortcut.Description = "SCRAP Screen Capture & Recording Platform"
$Shortcut.Save()

Write-Host "Portable app built at: $ExePath"
Write-Host "Distribution package: $ZipPath"
Write-Host "Desktop shortcut created at: $ShortcutPath"
