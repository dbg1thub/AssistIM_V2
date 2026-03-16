param(
    [string]$EnvFile = 'server/.env',
    [string]$DatabaseUrl = '',
    [string]$BindHost = '0.0.0.0',
    [int]$Port = 8000,
    [switch]$Reload
)

. (Join-Path $PSScriptRoot 'common.ps1')

$serverRoot = Split-Path $PSScriptRoot -Parent
$repoRoot = Split-Path $serverRoot -Parent
$envPath = if ([System.IO.Path]::IsPathRooted($EnvFile)) { $EnvFile } else { Join-Path $repoRoot $EnvFile }

if (Test-Path $envPath) {
    Import-EnvFile -Path $envPath
}
elseif (-not $DatabaseUrl) {
    throw "Env file not found: $envPath. Provide -DatabaseUrl or create server/.env"
}

if ($DatabaseUrl) {
    [Environment]::SetEnvironmentVariable('DATABASE_URL', $DatabaseUrl, 'Process')
}

$python = Resolve-PythonPath -ServerRoot $serverRoot
$args = @('-m', 'uvicorn', 'app.main:app', '--app-dir', 'server', '--host', $BindHost, '--port', $Port)
if ($Reload) {
    $args += '--reload'
}

Push-Location $repoRoot
try {
    & $python @args
}
finally {
    Pop-Location
}
