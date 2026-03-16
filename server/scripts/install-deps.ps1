param(
    [string]$VenvPath = 'server/.venv',
    [switch]$UpgradePip
)

$serverRoot = Split-Path $PSScriptRoot -Parent
$repoRoot = Split-Path $serverRoot -Parent
$requirementsFile = Join-Path $serverRoot 'requirements.txt'

$venvFullPath = if ([System.IO.Path]::IsPathRooted($VenvPath)) {
    $VenvPath
} else {
    Join-Path $repoRoot $VenvPath
}

$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) {
    throw 'python command not found.'
}

$venvPython = Join-Path $venvFullPath 'Scripts\python.exe'
if (-not (Test-Path $venvPython)) {
    & $python.Source -m venv $venvFullPath
    if (-not (Test-Path $venvPython)) {
        throw "Virtual environment creation failed: $venvPython"
    }
}

& $python.Source -m pip --python $venvPython install --upgrade pip
if ($LASTEXITCODE -ne 0) {
    throw 'Failed to bootstrap pip inside the virtual environment.'
}

if ($UpgradePip) {
    & $python.Source -m pip --python $venvPython install --upgrade setuptools wheel
    if ($LASTEXITCODE -ne 0) {
        throw 'Failed to upgrade setuptools/wheel inside the virtual environment.'
    }
}

& $python.Source -m pip --python $venvPython install -r $requirementsFile
if ($LASTEXITCODE -ne 0) {
    throw 'Failed to install backend dependencies.'
}

Write-Host "Dependencies installed into $venvFullPath"
