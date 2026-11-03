$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectRoot

$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    throw "Virtual environment not found. Create it with: python -m venv .venv"
}

& $Python -m pip install --upgrade pyinstaller pillow

$IconPng = Join-Path $ProjectRoot "assets\icon.png"
$IconIco = Join-Path $ProjectRoot "assets\icon.ico"

$IconScript = @"
from PIL import Image
image = Image.open(r'''$IconPng''').convert('RGBA')
image.save(r'''$IconIco''', format='ICO', sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)])
"@
& $Python -c $IconScript

& $Python -m PyInstaller --noconfirm --clean --noconsole --onedir `
    --name SCRAP `
    --icon $IconIco `
    --splash $IconPng `
    --add-data "assets;assets" `
    app_gui.py

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
Compress-Archive -Path (Join-Path $ProjectRoot "dist\SCRAP") -DestinationPath $ZipPath -CompressionLevel Optimal

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
