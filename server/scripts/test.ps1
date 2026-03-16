param(
    [string]$TestPath = 'tests',
    [switch]$VerboseOutput
)

. (Join-Path $PSScriptRoot 'common.ps1')

$serverRoot = Split-Path $PSScriptRoot -Parent
$python = Resolve-PythonPath -ServerRoot $serverRoot
$args = @('-m', 'pytest', $TestPath)
if ($VerboseOutput) {
    $args += '-vv'
}

Push-Location $serverRoot
try {
    & $python @args
}
finally {
    Pop-Location
}
