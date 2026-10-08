<#
.SYNOPSIS
  One-shot environment bootstrap for Windows.

  Creates .venv with a Python 3.12+ interpreter and installs the development
  dependencies from requirements-dev.txt (-e .[dev]). A valid existing .venv
  is reused; a broken one is recreated. Linux/macOS equivalent:
  scripts\bootstrap.sh

.EXAMPLE
  .\scripts\bootstrap.ps1                     # create/update .venv + install deps
  .\scripts\bootstrap.ps1 -Check              # also run pytest and edi doctor
  .\scripts\bootstrap.ps1 -Force              # recreate .venv from scratch
  .\scripts\bootstrap.ps1 -Python "C:\Python312\python.exe"
#>
[CmdletBinding()]
param(
    [switch]$Check,
    [switch]$Force,
    [string]$Python
)

$ErrorActionPreference = "Stop"
Set-Location -LiteralPath (Join-Path $PSScriptRoot "..")

$Venv = ".venv"
$VenvPython = Join-Path $Venv "Scripts\python.exe"
$VenvEdi = Join-Path $Venv "Scripts\edi.exe"

function Stop-Bootstrap {
    param([string]$Message, [int]$Code = 2)
    [Console]::Error.WriteLine("bootstrap.ps1: $Message")
    exit $Code
}

function Test-Py312 {
    param([string]$Exe, [string[]]$Prefix = @())
    try {
        & $Exe @Prefix -c "import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)" *> $null
        return ($LASTEXITCODE -eq 0)
    }
    catch {
        return $false
    }
}

function Get-Interpreter {
    foreach ($explicit in @($Python, $env:EDI_PYTHON)) {
        if (-not $explicit) { continue }
        if (-not (Test-Path -LiteralPath $explicit)) {
            Stop-Bootstrap "interpreter not found: $explicit"
        }
        if (-not (Test-Py312 -Exe $explicit)) {
            Stop-Bootstrap "interpreter is older than Python 3.12: $explicit"
        }
        return @{ Exe = $explicit; Prefix = @() }
    }

    $candidates = @(
        @{ Exe = "py"; Prefix = @("-3.12") },
        @{ Exe = "py"; Prefix = @() },
        @{ Exe = "python3.12"; Prefix = @() },
        @{ Exe = "python"; Prefix = @() }
    )
    foreach ($candidate in $candidates) {
        if (Get-Command $candidate.Exe -ErrorAction SilentlyContinue) {
            if (Test-Py312 -Exe $candidate.Exe -Prefix $candidate.Prefix) {
                return @{ Exe = $candidate.Exe; Prefix = $candidate.Prefix }
            }
        }
    }

    Stop-Bootstrap @"
no Python >= 3.12 interpreter found.
Install one, then re-run:
  winget install Python.Python.3.12
Or point at an existing interpreter:
  .\scripts\bootstrap.ps1 -Python `"C:\path\to\python.exe`"
  `$env:EDI_PYTHON = `"C:\path\to\python.exe`"
"@
}

function Invoke-Step {
    param([string]$Label, [string[]]$CommandLine)
    $exe = $CommandLine[0]
    $rest = @($CommandLine | Select-Object -Skip 1)
    & $exe @rest
    if ($LASTEXITCODE -ne 0) {
        Stop-Bootstrap "$Label failed (exit code $LASTEXITCODE)" 1
    }
}

$interp = Get-Interpreter
$venvValid = (Test-Path (Join-Path $Venv "pyvenv.cfg")) -and
    (Test-Path -LiteralPath $VenvPython) -and
    (Test-Py312 -Exe $VenvPython)

if ($Force) {
    Write-Host "bootstrap.ps1: -Force, recreating $Venv"
    Remove-Item -LiteralPath $Venv -Recurse -Force -ErrorAction SilentlyContinue
}
elseif ((Test-Path -LiteralPath $Venv) -and -not $venvValid) {
    Write-Host "bootstrap.ps1: existing $Venv is invalid or broken, recreating it"
    Remove-Item -LiteralPath $Venv -Recurse -Force -ErrorAction SilentlyContinue
}

if (-not (Test-Path -LiteralPath $Venv)) {
    $version = & $interp.Exe @($interp.Prefix + @("-V")) 2>&1
    Write-Host "bootstrap.ps1: creating $Venv with $($interp.Exe) ($version)"
    $venvCommand = @($interp.Exe) + @($interp.Prefix) + @("-m", "venv", $Venv)
    Invoke-Step "venv creation" $venvCommand
}
else {
    Write-Host "bootstrap.ps1: reusing existing $Venv"
}

Write-Host "bootstrap.ps1: installing development dependencies"
Invoke-Step "pip self-upgrade" @($VenvPython, "-m", "pip", "install", "--quiet", "--upgrade", "pip")
Invoke-Step "dependency install" @($VenvPython, "-m", "pip", "install", "--quiet", "-r", "requirements-dev.txt")

if ($Check) {
    Write-Host "bootstrap.ps1: running test suite"
    Invoke-Step "pytest" @($VenvPython, "-m", "pytest", "-q")
    Write-Host "bootstrap.ps1: host probe"
    Invoke-Step "edi doctor" @($VenvEdi, "doctor")
}

Write-Host @"
bootstrap.ps1: done.
Next steps:
  .\$Venv\Scripts\Activate.ps1      # or call .\$Venv\Scripts\edi.exe directly
  edi doctor
  edi config --wizard               # optional one-time defaults
"@
