$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectRoot

$BuildFolder = Join-Path $ProjectRoot "build"
$DistFolder = Join-Path $ProjectRoot "dist"
if (Test-Path $BuildFolder) { Remove-Item $BuildFolder -Recurse -Force }
if (Test-Path $DistFolder) { Remove-Item $DistFolder -Recurse -Force }

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

$CertificatePath = $env:SCRAP_CERTIFICATE_PFX
$CertificatePassword = $env:SCRAP_CERTIFICATE_PASSWORD
$TimestampUrl = if ($env:SCRAP_TIMESTAMP_URL) { $env:SCRAP_TIMESTAMP_URL } else { "http://timestamp.digicert.com" }

if ($CertificatePath) {
    if (-not (Test-Path $CertificatePath)) {
        throw "SCRAP_CERTIFICATE_PFX does not point to an existing certificate."
    }

    $SignTool = Get-ChildItem "C:\Program Files (x86)\Windows Kits\10\bin" -Filter signtool.exe -Recurse -ErrorAction SilentlyContinue |
        Sort-Object FullName -Descending |
        Select-Object -First 1
    if (-not $SignTool) {
        throw "Signing was requested, but signtool.exe was not found."
    }

    $SignArguments = @(
        "sign", "/fd", "SHA256", "/tr", $TimestampUrl, "/td", "SHA256",
        "/f", $CertificatePath
    )
    if ($CertificatePassword) {
        $SignArguments += @("/p", $CertificatePassword)
    }
    $SignArguments += $ExePath

    & $SignTool.FullName $SignArguments
    if ($LASTEXITCODE -ne 0) {
        throw "Authenticode signing failed."
    }
} else {
    Write-Host "Signing skipped: set SCRAP_CERTIFICATE_PFX to sign SCRAP.exe."
}

$ReadmePath = Join-Path $ProjectRoot "dist\README.txt"
@"
SCRAP Screen Capture and Recording Platform

1. Download SCRAP-Portable.zip only from the official SCRAP GitHub Releases page.
2. Extract all files, keeping SCRAP.exe and README.txt together.
3. Run the extracted SCRAP.exe. Do not run SCRAP.exe from inside a source-code ZIP.
No Python installation or setup is required.

SCRAP is a screen-recording utility. It records only the screen/audio sources
you select and saves files locally. It does not contain or require a browser
extension or telemetry service.

Recordings are saved automatically under the current user's Videos folder:
Videos\ScreenRecordings

Verification and Windows warnings
- Verify the SCRAP.exe SHA-256 hash listed in SHA256SUMS.txt.
- Windows SmartScreen or antivirus may warn about an unsigned or newly released
  application. If the hash does not match this release's hashes, delete the file.
- Do not grant overrides to a copy downloaded from an unofficial source.
- False positives should be reported to your antivirus vendor with the official
  release URL and SHA-256 hash. If you are the maintainer, submit the signed
  binary to Microsoft and/or VirusTotal for reputation review.
"@ | Set-Content -Path $ReadmePath -Encoding ASCII

$PackageFolder = Join-Path $ProjectRoot "dist\SCRAP-Portable"
if (Test-Path $PackageFolder) {
    Remove-Item $PackageFolder -Recurse -Force
}
New-Item -ItemType Directory -Path $PackageFolder | Out-Null
Copy-Item $ExePath -Destination $PackageFolder
Copy-Item $ReadmePath -Destination $PackageFolder

$HashFile = Join-Path $PackageFolder "SHA256SUMS.txt"
Get-FileHash $ExePath -Algorithm SHA256 |
    ForEach-Object { "$($_.Hash.ToLower())  SCRAP.exe" } |
    Set-Content -Path $HashFile -Encoding ASCII

$ZipPath = Join-Path $ProjectRoot "dist\SCRAP-Portable.zip"
if (Test-Path $ZipPath) { Remove-Item $ZipPath -Force }
Start-Sleep -Seconds 2
Compress-Archive -Path (Join-Path $PackageFolder "*") -DestinationPath $ZipPath -CompressionLevel Optimal

Write-Host "Portable app: $ExePath"
Write-Host "Distribution package: $ZipPath"
