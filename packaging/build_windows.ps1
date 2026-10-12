# Build Clicks-Auto for Windows into a portable ZIP.
#
#   powershell -ExecutionPolicy Bypass -File packaging/build_windows.ps1
#
# Optional environment switches:
#   $env:BUNDLE_PLAYWRIGHT_BROWSERS = "1"   # also ship a Chromium copy (~150 MB bigger)
#   $env:SKIP_TESTS = "1"                   # skip the pytest run before packaging

param(
    [string]$Python = "python",
    [string]$Version = "1.0.1",
    [switch]$SkipTests,
    [switch]$BundleBrowser
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $root

Write-Host "== Clicks-Auto build ==" -ForegroundColor Cyan
Write-Host "Repository : $root"

Write-Host "`n[1/5] Installing build dependencies..." -ForegroundColor Cyan
& $Python -m pip install --upgrade pip
& $Python -m pip install -r requirements-dev.txt

if (-not $SkipTests -and -not $env:SKIP_TESTS) {
    Write-Host "`n[2/5] Running the test suite..." -ForegroundColor Cyan
    & $Python -m pytest -q
    if ($LASTEXITCODE -ne 0) { throw "tests failed - not building the release" }
} else {
    Write-Host "`n[2/5] Tests skipped." -ForegroundColor Yellow
}

Write-Host "`n[3/5] Generating icons..." -ForegroundColor Cyan
& $Python packaging/make_icons.py

Write-Host "`n[4/5] Packaging with PyInstaller..." -ForegroundColor Cyan
if ($BundleBrowser) {
    $env:BUNDLE_PLAYWRIGHT_BROWSERS = "1"
    & $Python -m playwright install chromium
}
& $Python -m PyInstaller packaging/clicks_auto.spec --noconfirm --clean --distpath dist --workpath build

$distDir = Join-Path $root "dist/Clicks-Auto"
if (-not (Test-Path $distDir)) { throw "PyInstaller did not produce $distDir" }

# A README next to the executable so the ZIP is self explanatory.
$readme = @"
Clicks-Auto $Version - portable build
=====================================

1. Unzip this folder anywhere (Desktop, USB stick, ...).
2. Run Clicks-Auto.exe
3. Click "Record Session" to capture your first automation.
4. Press "Run" to play it back, once or in a loop.

clicks-auto-cli.exe is the headless runner:

    clicks-auto-cli.exe run "C:\path\script.json" --loops 5
    clicks-auto-cli.exe list
    clicks-auto-cli.exe browsers

Your scripts, logs and browser profile live in
%LOCALAPPDATA%\Clicks-Auto  (Settings -> Files and folders opens it).

Requires a Chromium based browser: Brave (recommended), Google Chrome or
Microsoft Edge. Settings -> Browser can also download Playwright's own
Chromium if none of those are installed.
"@
Set-Content -Path (Join-Path $distDir "README.txt") -Value $readme -Encoding UTF8

Write-Host "`n[5/5] Creating the ZIP..." -ForegroundColor Cyan
$zipName = "Clicks-Auto-$Version-win64.zip"
$zipPath = Join-Path $root "dist/$zipName"
if (Test-Path $zipPath) { Remove-Item $zipPath }
Compress-Archive -Path "$distDir/*" -DestinationPath $zipPath -CompressionLevel Optimal

$hash = (Get-FileHash $zipPath -Algorithm SHA256).Hash
Set-Content -Path "$zipPath.sha256" -Value "$hash  $zipName" -Encoding ASCII

Write-Host "`nBuild finished." -ForegroundColor Green
Write-Host "  folder : $distDir"
Write-Host "  zip    : $zipPath"
Write-Host "  sha256 : $hash"
