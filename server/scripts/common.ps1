function Import-EnvFile {
    param([Parameter(Mandatory = $true)][string]$Path)

    if (-not (Test-Path $Path)) {
        throw "Env file not found: $Path"
    }

    Get-Content $Path | ForEach-Object {
        $line = $_.Trim()
        if (-not $line -or $line.StartsWith('#') -or -not $line.Contains('=')) {
            return
        }

        $parts = $line.Split('=', 2)
        $name = $parts[0].Trim()
        $value = $parts[1].Trim()

        if ($value.Length -ge 2) {
            $isDoubleQuoted = $value.StartsWith('"') -and $value.EndsWith('"')
            $isSingleQuoted = $value.StartsWith("'") -and $value.EndsWith("'")
            if ($isDoubleQuoted -or $isSingleQuoted) {
                $value = $value.Substring(1, $value.Length - 2)
            }
        }

        [Environment]::SetEnvironmentVariable($name, $value, 'Process')
    }
}

function Resolve-PythonPath {
    param([Parameter(Mandatory = $true)][string]$ServerRoot)

    $activeEnvPython = Get-Command python -ErrorAction SilentlyContinue
    $hasActivatedEnv = [bool]$env:CONDA_PREFIX -or [bool]$env:VIRTUAL_ENV

    if ($hasActivatedEnv -and $activeEnvPython) {
        return $activeEnvPython.Source
    }

    $venvPython = Join-Path $ServerRoot '.venv\Scripts\python.exe'
    if (Test-Path $venvPython) {
        return (Resolve-Path $venvPython).Path
    }

    if ($activeEnvPython) {
        return $activeEnvPython.Source
    }

    throw 'Python executable not found. Install Python or create server/.venv first.'
}

function Parse-PostgresUrl {
    param([string]$DatabaseUrl)

    if (-not $DatabaseUrl) {
        return $null
    }

    try {
        $uriString = $DatabaseUrl -replace '^postgresql(\+[^:]+)?://', 'postgresql://'
        $uri = [System.Uri]$uriString
        $userInfo = if ($uri.UserInfo) { $uri.UserInfo.Split(':', 2) } else { @() }

        return [pscustomobject]@{
            User = if ($userInfo.Length -ge 1) { [System.Uri]::UnescapeDataString($userInfo[0]) } else { '' }
            Password = if ($userInfo.Length -ge 2) { [System.Uri]::UnescapeDataString($userInfo[1]) } else { '' }
            Host = if ($uri.Host) { $uri.Host } else { 'localhost' }
            Port = if ($uri.Port -gt 0) { $uri.Port } else { 5432 }
            Database = $uri.AbsolutePath.TrimStart('/')
        }
    }
    catch {
        return $null
    }
}

function Get-PsqlPath {
    param([string]$ExplicitPath = '')

    if ($ExplicitPath) {
        if (-not (Test-Path $ExplicitPath)) {
            throw "psql.exe not found at $ExplicitPath"
        }
        return (Resolve-Path $ExplicitPath).Path
    }

    $psql = Get-Command psql.exe -ErrorAction SilentlyContinue
    if ($psql) {
        return $psql.Source
    }

    $service = Get-Service | Where-Object { $_.Name -like 'postgresql-*' } | Select-Object -First 1
    if (-not $service) {
        throw 'PostgreSQL service not found and psql.exe is not on PATH.'
    }

    $qc = sc.exe qc $service.Name | Out-String
    $line = ($qc -split "`r?`n" | Where-Object { $_ -match 'BINARY_PATH_NAME' } | Select-Object -First 1)
    if (-not $line) {
        throw "Unable to resolve PostgreSQL binary path from service $($service.Name)."
    }

    $pathPart = ($line -replace '.*BINARY_PATH_NAME\s+:\s*', '').Trim()
    if ($pathPart.StartsWith('"')) {
        $closingQuote = $pathPart.IndexOf('"', 1)
        if ($closingQuote -lt 1) {
            throw "Invalid PostgreSQL service binary path: $pathPart"
        }
        $serviceBinary = $pathPart.Substring(1, $closingQuote - 1)
    }
    elseif ($pathPart -match '^(.+?pg_ctl\.exe)') {
        $serviceBinary = $matches[1]
    }
    elseif ($pathPart -match '^(.+?postgres\.exe)') {
        $serviceBinary = $matches[1]
    }
    else {
        $serviceBinary = ($pathPart -split '\s+')[0]
    }

    $binDir = Split-Path $serviceBinary -Parent
    $resolved = Join-Path $binDir 'psql.exe'
    if (-not (Test-Path $resolved)) {
        throw "psql.exe not found at $resolved"
    }

    return $resolved
}
