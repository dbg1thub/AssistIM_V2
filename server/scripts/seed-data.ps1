param(
    [string]$EnvFile = 'server/.env',
    [string]$DatabaseUrl = '',
    [string]$UploadDir = '',
    [switch]$Reset
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
if ($UploadDir) {
    [Environment]::SetEnvironmentVariable('UPLOAD_DIR', $UploadDir, 'Process')
}

$python = Resolve-PythonPath -ServerRoot $serverRoot
$args = @('-m', 'app.seed')
if ($DatabaseUrl) {
    $args += @('--database-url', $DatabaseUrl)
}
if ($UploadDir) {
    $args += @('--upload-dir', $UploadDir)
}
if ($Reset) {
    $args += '--reset'
}

Push-Location $serverRoot
try {
    & $python @args
}
finally {
    Pop-Location
}
