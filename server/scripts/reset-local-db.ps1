param(
    [switch]$ConfirmReset,
    [string]$EnvFile = 'server/.env',
    [string]$DatabaseUrl = '',
    [string]$PsqlPath = ''
)

. (Join-Path $PSScriptRoot 'common.ps1')

function Assert-LocalDatabaseHost {
    param([Parameter(Mandatory = $true)][string]$HostName)

    $normalized = $HostName.Trim().ToLowerInvariant()
    if ($normalized.StartsWith('[') -and $normalized.EndsWith(']')) {
        $normalized = $normalized.Substring(1, $normalized.Length - 2)
    }

    $localHosts = @('localhost', '127.0.0.1', '::1', '0:0:0:0:0:0:0:1')
    if ($localHosts -notcontains $normalized) {
        throw "Refusing to reset non-local database host '$HostName'. This script is local-only."
    }
}

function Assert-ResetConfirmed {
    param(
        [Parameter(Mandatory = $true)][bool]$Confirmed,
        [Parameter(Mandatory = $true)][string]$DatabaseKind,
        [Parameter(Mandatory = $true)][string]$DatabaseName,
        [string]$HostName = '',
        [int]$Port = 0
    )

    Write-Host 'Target database:'
    Write-Host ("  type: {0}" -f $DatabaseKind)
    Write-Host ("  host: {0}" -f $(if ($HostName) { $HostName } else { 'n/a' }))
    Write-Host ("  port: {0}" -f $(if ($Port -gt 0) { $Port } else { 'n/a' }))
    Write-Host ("  name: {0}" -f $DatabaseName)

    if (-not $Confirmed) {
        throw 'Refusing to reset without -ConfirmReset.'
    }
}

function Assert-SafePostgresDatabaseName {
    param([Parameter(Mandatory = $true)][string]$DatabaseName)

    $normalized = $DatabaseName.Trim().ToLowerInvariant()
    if (@('postgres', 'template0', 'template1') -contains $normalized) {
        throw "Refusing to reset protected PostgreSQL database '$DatabaseName'."
    }
}

function Invoke-CheckedCommand {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter(Mandatory = $true)][string[]]$Arguments
    )

    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed with exit code ${LASTEXITCODE}: $FilePath $($Arguments -join ' ')"
    }
}

function Reset-PostgresDatabase {
    param(
        [Parameter(Mandatory = $true)]$DbConfig,
        [Parameter(Mandatory = $true)][string]$ResolvedPsql
    )

    Assert-LocalDatabaseHost -HostName $DbConfig.Host
    Assert-SafePostgresDatabaseName -DatabaseName $DbConfig.Database

    $sql = @"
SELECT pg_terminate_backend(pid)
FROM pg_stat_activity
WHERE datname = :'db_name'
  AND pid <> pg_backend_pid();

DROP DATABASE IF EXISTS :"db_name";
CREATE DATABASE :"db_name";
"@

    $temp = New-TemporaryFile
    $hadPgPassword = Test-Path Env:PGPASSWORD
    $previousPgPassword = $env:PGPASSWORD

    try {
        Set-Content -Path $temp -Value $sql -Encoding utf8
        if ($DbConfig.Password) {
            $env:PGPASSWORD = $DbConfig.Password
        }

        $arguments = @(
            '-v', 'ON_ERROR_STOP=1',
            '-v', "db_name=$($DbConfig.Database)",
            '-h', $DbConfig.Host,
            '-p', ([string]$DbConfig.Port),
            '-d', 'postgres',
            '-f', ([string]$temp)
        )
        if ($DbConfig.User) {
            $arguments = @('-U', $DbConfig.User) + $arguments
        }
        Invoke-CheckedCommand -FilePath $ResolvedPsql -Arguments $arguments
    }
    finally {
        Remove-Item $temp -Force -ErrorAction SilentlyContinue
        if ($hadPgPassword) {
            $env:PGPASSWORD = $previousPgPassword
        }
        else {
            Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue
        }
    }
}

function Resolve-SqliteDatabasePath {
    param(
        [Parameter(Mandatory = $true)][string]$SqliteUrl,
        [Parameter(Mandatory = $true)][string]$ServerRoot
    )

    if ($SqliteUrl -notmatch '^sqlite(\+[^:]+)?:///(.+)$') {
        throw "Unsupported SQLite DATABASE_URL format: $SqliteUrl"
    }

    $rawPath = [System.Uri]::UnescapeDataString($matches[2])
    if (-not $rawPath -or $rawPath -eq ':memory:') {
        throw 'SQLite DATABASE_URL must point to a file.'
    }

    if ([System.IO.Path]::IsPathRooted($rawPath)) {
        return $rawPath
    }
    return (Join-Path $ServerRoot $rawPath)
}

function Reset-SqliteDatabase {
    param([Parameter(Mandatory = $true)][string]$DatabasePath)

    $parent = Split-Path $DatabasePath -Parent
    if ($parent) {
        New-Item -ItemType Directory -Path $parent -Force | Out-Null
    }

    Remove-Item -LiteralPath $DatabasePath -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath "${DatabasePath}-wal" -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath "${DatabasePath}-shm" -Force -ErrorAction SilentlyContinue
}

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
$databaseUrlValue = $env:DATABASE_URL.Trim()

if ($databaseUrlValue -match '^postgres(?:ql)?(\+[^:]+)?://') {
    $dbConfig = Parse-PostgresUrl -DatabaseUrl $databaseUrlValue
    if (-not $dbConfig -or -not $dbConfig.Database) {
        throw "Invalid PostgreSQL DATABASE_URL: $databaseUrlValue"
    }

    Assert-LocalDatabaseHost -HostName $dbConfig.Host
    Assert-SafePostgresDatabaseName -DatabaseName $dbConfig.Database

    Assert-ResetConfirmed `
        -Confirmed ([bool]$ConfirmReset) `
        -DatabaseKind 'postgresql' `
        -DatabaseName $dbConfig.Database `
        -HostName $dbConfig.Host `
        -Port $dbConfig.Port

    $psql = Get-PsqlPath -ExplicitPath $PsqlPath
    Reset-PostgresDatabase -DbConfig $dbConfig -ResolvedPsql $psql
}
elseif ($databaseUrlValue -match '^sqlite(\+[^:]+)?://') {
    $sqlitePath = Resolve-SqliteDatabasePath -SqliteUrl $databaseUrlValue -ServerRoot $serverRoot

    Assert-ResetConfirmed `
        -Confirmed ([bool]$ConfirmReset) `
        -DatabaseKind 'sqlite' `
        -DatabaseName $sqlitePath

    Reset-SqliteDatabase -DatabasePath $sqlitePath
}
else {
    throw "Unsupported DATABASE_URL driver: $databaseUrlValue"
}

Push-Location $serverRoot
try {
    Invoke-CheckedCommand -FilePath $python -Arguments @('-m', 'alembic', 'upgrade', 'head')
    Invoke-CheckedCommand -FilePath $python -Arguments @('-m', 'app.ops.seed_test_users')
}
finally {
    Pop-Location
}

Write-Host 'Database reset completed.'
