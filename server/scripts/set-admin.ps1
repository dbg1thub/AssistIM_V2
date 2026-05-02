param(
    [Parameter(Mandatory = $true)][string]$Username,
    [ValidateSet('user', 'admin')][string]$Role = 'admin',
    [string]$Actor = 'server-script',
    [string]$EnvFile = 'server/.env',
    [string]$DatabaseUrl = ''
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

if (-not $env:DATABASE_URL) {
    throw 'DATABASE_URL is not set.'
}

$python = Resolve-PythonPath -ServerRoot $serverRoot

Push-Location $serverRoot
try {
    & $python -m app.ops.set_admin --username $Username --role $Role --actor $Actor
}
finally {
    Pop-Location
}
