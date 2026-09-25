# Code-sign RELAY's executables (run after build.ps1). Needs a code-signing
# certificate and signtool.exe (Windows SDK). Nothing here is run automatically.
#
#   powershell -ExecutionPolicy Bypass -File packaging\sign.ps1 -Thumbprint <cert SHA1>
#   powershell -ExecutionPolicy Bypass -File packaging\sign.ps1 -PfxPath cert.pfx
#
# Without a signature Windows SmartScreen warns on first run of a DOWNLOADED copy
# ("More info" -> "Run anyway"). Copies from a USB stick, and the from-source setup
# (python.exe is already signed), don't get that warning.
param(
    [string]$Thumbprint = "",
    [string]$PfxPath = "",
    [string]$TimestampUrl = "http://timestamp.digicert.com"
)
$ErrorActionPreference = "Stop"

$signtool = Get-ChildItem "${env:ProgramFiles(x86)}\Windows Kits\10\bin\*\x64\signtool.exe" `
    -ErrorAction SilentlyContinue | Sort-Object FullName -Descending | Select-Object -First 1
if (-not $signtool) { throw "signtool.exe not found - install the Windows 10/11 SDK." }
if (-not $Thumbprint -and -not $PfxPath) { throw "Give -Thumbprint or -PfxPath." }

$files = @("dist\relay\relay.exe", "dist\relay\relay-cli.exe")
foreach ($f in $files) {
    if (-not (Test-Path $f)) { throw "$f not found - run packaging\build.ps1 first." }
    $signArgs = @("sign", "/fd", "SHA256", "/tr", $TimestampUrl, "/td", "SHA256")
    if ($Thumbprint) { $signArgs += @("/sha1", $Thumbprint) } else { $signArgs += @("/f", $PfxPath) }
    & $signtool.FullName @signArgs $f
    if ($LASTEXITCODE -ne 0) { throw "signing failed for $f" }
    & $signtool.FullName verify /pa $f
}
Write-Host "Signed and verified: $($files -join ', ')"
