<#
.SYNOPSIS
  Workspace startup script for the Enterprise Document Intelligence reference.

  Bootstraps the project virtual environment, verifies dev dependencies,
  prints a quick host probe, optionally runs the test suite, then starts the
  read-only web panel (edi web) until Ctrl+C.

.EXAMPLE
  .\scripts\startup.ps1                          # web panel on 127.0.0.1:4099
  .\scripts\startup.ps1 -Port 8080 -Hostname 0.0.0.0
  .\scripts\startup.ps1 -Test                    # run pytest before starting
  .\scripts\startup.ps1 -SkipInstall             # skip dependency bootstrap
  .\scripts\startup.ps1 -NoWeb                   # doctor (+ tests) only, no server
#>
[CmdletBinding()]
param(
    [ValidateRange(1, 65535)]
    [int]$Port = 4099,
    [string]$Hostname = "127.0.0.1",
    [switch]$Test,
    [switch]$SkipInstall,
    [switch]$NoWeb
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

$venvPython = Join-Path $repoRoot ".venv\Scripts\python.exe"

function Invoke-Step {
    param([string]$Name, [scriptBlock]$Block)
    Write-Host "[startup] $Name ..."
    & $Block
    if ($LASTEXITCODE -ne 0) {
        throw "[startup] step failed: $Name (exit $LASTEXITCODE)"
    }
}

# 1. virtual environment (never install ML/provider packages into it)
if (-not (Test-Path $venvPython)) {
    Write-Host "[startup] creating .venv ..."
    if (Get-Command py -ErrorAction SilentlyContinue) {
        & py -3.12 -m venv .venv
    } else {
        & python -m venv .venv
    }
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path $venvPython)) {
        throw "[startup] failed to create .venv"
    }
}

# 2. dev dependencies (pytest, ruff, mypy, editable install)
if (-not $SkipInstall) {
    & $venvPython -c "import pytest, ruff, mypy, edi_reference"
    if ($LASTEXITCODE -ne 0) {
        Invoke-Step "installing requirements-dev.txt" {
            & $venvPython -m pip install --disable-pip-version-check -q -r requirements-dev.txt
        }
    }
}

# 3. quick host probe (informational; GPU absence does not fail the core)
Write-Host "[startup] host probe:"
& $venvPython -m edi_reference.cli doctor

# 4. optional test run (deterministic; skips PostgreSQL integration without DSN)
if ($Test) {
    Invoke-Step "running test suite" {
        & $venvPython -m pytest -q
    }
}

# 5. read-only web panel (blocks until Ctrl+C)
if ($NoWeb) {
    Write-Host "[startup] done (-NoWeb: skipping edi web)"
    return 0
}

Write-Host "[startup] starting edi web on http://${Hostname}:${Port}/ (Ctrl+C to stop)"
& $venvPython -m edi_reference.cli web --hostname $Hostname --port $Port
