<#
.SYNOPSIS
    Starts Scrum Poker and (optionally) publishes it with a login-free public URL.

.DESCRIPTION
    Without options this just starts the local server on http://localhost:<port>.

    -Cloudflare starts a Cloudflare "quick tunnel" in addition. That gives you a
    public https://<random>.trycloudflare.com address that anybody can open
    WITHOUT any account or login - not even you need one. cloudflared.exe is
    downloaded once into .\tools on first use (you are asked before it happens).

.EXAMPLE
    .\share.ps1
    .\share.ps1 -Cloudflare
    .\share.ps1 -Port 8080 -Cloudflare
#>
[CmdletBinding()]
param(
    [int]$Port = 8000,
    [switch]$Cloudflare
)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$toolsDir = Join-Path $root "tools"
$cloudflared = Join-Path $toolsDir "cloudflared.exe"

function Test-PortInUse([int]$p) {
    return [bool](Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue)
}

function Get-Cloudflared {
    if (Test-Path $cloudflared) { return }

    Write-Host ""
    Write-Host "cloudflared.exe is not present yet." -ForegroundColor Yellow
    Write-Host "It will be downloaded (~35 MB) from the official Cloudflare release page:"
    Write-Host "  https://github.com/cloudflare/cloudflared/releases/latest" -ForegroundColor DarkGray
    $answer = Read-Host "Download it now? [y/N]"
    if ($answer -notmatch '^(y|yes|j|ja)$') {
        throw "Aborted - cloudflared is required for -Cloudflare."
    }

    New-Item -ItemType Directory -Path $toolsDir -Force | Out-Null
    $url = "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe"
    Write-Host "Downloading cloudflared..." -ForegroundColor Cyan
    $progress = $ProgressPreference
    $ProgressPreference = "SilentlyContinue"
    try {
        Invoke-WebRequest -Uri $url -OutFile $cloudflared -UseBasicParsing
    } finally {
        $ProgressPreference = $progress
    }
    Write-Host "Saved to $cloudflared" -ForegroundColor Green
}

# --------------------------------------------------------------- the server
if (Test-PortInUse $Port) {
    Write-Host "Server already running on port $Port - reusing it." -ForegroundColor DarkGray
} else {
    Write-Host "Starting Scrum Poker on port $Port ..." -ForegroundColor Cyan
    Start-Process -FilePath "python" -ArgumentList @("$root\server.py", "--port", "$Port") -WorkingDirectory $root
    for ($i = 0; $i -lt 20 -and -not (Test-PortInUse $Port); $i++) { Start-Sleep -Milliseconds 300 }
    if (-not (Test-PortInUse $Port)) { throw "The server did not start on port $Port." }
}

Write-Host ""
Write-Host "  Local:  http://localhost:$Port" -ForegroundColor Green

if (-not $Cloudflare) {
    Write-Host ""
    Write-Host "To share it with the team without any login for them:" -ForegroundColor Yellow
    Write-Host "  a) VS Code -> Ports view -> Forward a Port -> $Port -> right-click -> Port Visibility -> Public"
    Write-Host "  b) or run:  .\share.ps1 -Cloudflare      (nobody needs an account at all)"
    return
}

# ------------------------------------------------------------- the tunnel
Get-Cloudflared

Write-Host ""
Write-Host "Starting a public Cloudflare quick tunnel (no login for anyone)..." -ForegroundColor Cyan
Write-Host "Keep this window open - closing it ends the tunnel." -ForegroundColor DarkGray
Write-Host ""

# cloudflared writes its banner (including the URL) to stderr.
& $cloudflared tunnel --url "http://localhost:$Port" --no-autoupdate 2>&1 | ForEach-Object {
    $line = "$_"
    if ($line -match 'https://[a-z0-9-]+\.trycloudflare\.com') {
        Write-Host ""
        Write-Host "  PUBLIC URL:  $($Matches[0])" -ForegroundColor Green
        Write-Host "  Send this link to the team - it opens without any login." -ForegroundColor Green
        Write-Host ""
    } elseif ($line -notmatch 'INF|WRN|DBG') {
        Write-Host $line -ForegroundColor DarkGray
    }
}
