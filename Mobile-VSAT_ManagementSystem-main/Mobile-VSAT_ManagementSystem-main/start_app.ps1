$ErrorActionPreference = "Stop"

# Get script directory
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

# Check for venv
$VenvPath = "..\..\.venv"
if (-not (Test-Path $VenvPath)) {
    Write-Error "Virtual environment not found at $VenvPath! Please run installation first."
}

# Run App
Write-Host "Starting Mobile VSAT Management System..." -ForegroundColor Cyan
& "$VenvPath\Scripts\python.exe" main.py
