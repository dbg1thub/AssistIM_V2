param(
    [string]$EnvFile = 'server/.env',
    [string]$PsqlPath = '',
    [string]$DatabaseName = '',
    [string]$SuperUser = '',
    [string]$MaintenanceDb = 'postgres',
    [string]$Password = '',
    [string]$DbHost = '',
    [int]$Port = 0
)

. (Join-Path $PSScriptRoot 'common.ps1')

$serverRoot = Split-Path $PSScriptRoot -Parent
$repoRoot = Split-Path $serverRoot -Parent
$envPath = if ([System.IO.Path]::IsPathRooted($EnvFile)) { $EnvFile } else { Join-Path $repoRoot $EnvFile }

if (Test-Path $envPath) {
    Import-EnvFile -Path $envPath
    $dbConfig = Parse-PostgresUrl -DatabaseUrl $env:DATABASE_URL
    if ($dbConfig) {
        if (-not $DatabaseName) { $DatabaseName = $dbConfig.Database }
        if (-not $SuperUser) { $SuperUser = $dbConfig.User }
        if (-not $Password) { $Password = $dbConfig.Password }
        if (-not $DbHost) { $DbHost = $dbConfig.Host }
        if ($Port -le 0) { $Port = $dbConfig.Port }
    }
}

if (-not $DatabaseName) { $DatabaseName = 'assistim' }
if (-not $SuperUser) { $SuperUser = 'postgres' }
if (-not $DbHost) { $DbHost = 'localhost' }
if ($Port -le 0) { $Port = 5432 }

$psql = Get-PsqlPath -ExplicitPath $PsqlPath
if (-not $Password) {
    $secure = Read-Host -Prompt "PostgreSQL password for user '$SuperUser'" -AsSecureString
    $Password = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure))
}

$env:PGPASSWORD = $Password

$sql = @"
SELECT format('CREATE DATABASE "%s"', :'db_name')
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = :'db_name')\gexec
"@

$temp = New-TemporaryFile
Set-Content -Path $temp -Value $sql -Encoding utf8

try {
    & $psql -v ON_ERROR_STOP=1 -v db_name=$DatabaseName -U $SuperUser -h $DbHost -p $Port -d $MaintenanceDb -f $temp
}
finally {
    Remove-Item $temp -Force -ErrorAction SilentlyContinue
    Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue
}

Write-Host ("Database '{0}' is ready on {1}:{2}." -f $DatabaseName, $DbHost, $Port)
