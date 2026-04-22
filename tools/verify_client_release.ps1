param(
    [string]$ReleaseRoot = "dist\client\release",
    [string]$PackageRoot = "dist\client\package\AssistIM",
    [string]$ExpectedVersion = "",
    [string]$ExpectedServerHost = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptDir "..")
$ReleasePath = Join-Path $RepoRoot $ReleaseRoot
$PackagePath = Join-Path $RepoRoot $PackageRoot
$LatestPath = Join-Path $ReleasePath "latest.json"
$VersionPath = Join-Path $PackagePath "version.json"
$ConfigPath = Join-Path $PackagePath "data\config.json"
$ManifestPath = Join-Path $PackagePath "manifest.json"
$RequiredQssPaths = @(
    "client/ui/styles/qss/dark/chat_interface.qss",
    "client/ui/styles/qss/light/chat_interface.qss"
)
$RequiredMultimediaPluginPaths = @(
    "PySide6/qt-plugins/multimedia/ffmpegmediaplugin.dll",
    "PySide6/qt-plugins/multimedia/windowsmediaplugin.dll"
)
$CudaRuntimeDlls = @("cudart64_12.dll", "cublas64_12.dll", "cublaslt64_12.dll")

function Assert-FileExists {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "Missing file: $Path"
    }
}

function Assert-DirectoryExists {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path -PathType Container)) {
        throw "Missing directory: $Path"
    }
}

Assert-DirectoryExists -Path $PackagePath
Assert-DirectoryExists -Path $ReleasePath
Assert-FileExists -Path $LatestPath
Assert-FileExists -Path $VersionPath
Assert-FileExists -Path $ConfigPath
Assert-FileExists -Path $ManifestPath

$latest = Get-Content -Raw -LiteralPath $LatestPath | ConvertFrom-Json
$version = Get-Content -Raw -LiteralPath $VersionPath | ConvertFrom-Json
$config = Get-Content -Raw -LiteralPath $ConfigPath | ConvertFrom-Json
$manifest = Get-Content -Raw -LiteralPath $ManifestPath | ConvertFrom-Json

if (-not [string]::IsNullOrWhiteSpace($ExpectedVersion)) {
    if ([string]$version.version -ne $ExpectedVersion) {
        throw "Version mismatch. Expected $ExpectedVersion, got $($version.version)"
    }
    if ([string]$latest.version -ne $ExpectedVersion) {
        throw "Latest version mismatch. Expected $ExpectedVersion, got $($latest.version)"
    }
}

if (-not [string]::IsNullOrWhiteSpace($ExpectedServerHost)) {
    if ($null -eq $config.PSObject.Properties["Server"]) {
        throw "Packaged config has no Server section"
    }
    if ([string]$config.Server.Host -ne $ExpectedServerHost) {
        throw "Server host mismatch. Expected $ExpectedServerHost, got $($config.Server.Host)"
    }
}

$zipPath = Join-Path $ReleasePath ([string]$latest.package)
Assert-FileExists -Path $zipPath
$zipHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $zipPath).Hash.ToLowerInvariant()
if ($zipHash -ne [string]$latest.sha256) {
    throw "Zip SHA256 mismatch"
}

$optionalPackages = @()
if ($null -ne $latest.PSObject.Properties["optional_packages"]) {
    $optionalPackages = @($latest.optional_packages)
}
foreach ($optionalPackage in $optionalPackages) {
    if ($null -eq $optionalPackage.PSObject.Properties["package"]) {
        throw "Optional package entry is missing package name"
    }
    $optionalZipPath = Join-Path $ReleasePath ([string]$optionalPackage.package)
    Assert-FileExists -Path $optionalZipPath
    if ($null -ne $optionalPackage.PSObject.Properties["sha256"]) {
        $optionalZipHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $optionalZipPath).Hash.ToLowerInvariant()
        if ($optionalZipHash -ne [string]$optionalPackage.sha256) {
            throw "Optional package SHA256 mismatch for $($optionalPackage.package)"
        }
    }
}

$forbiddenExtensions = @(".gguf", ".bin", ".safetensors")
$forbiddenFiles = @(Get-ChildItem -LiteralPath $PackagePath -Recurse -File |
    Where-Object { $forbiddenExtensions -contains $_.Extension.ToLowerInvariant() })
if ($forbiddenFiles.Count -gt 0) {
    $paths = ($forbiddenFiles | Select-Object -ExpandProperty FullName) -join [System.Environment]::NewLine
    throw "Model weight files must not be packaged:$([System.Environment]::NewLine)$paths"
}

$pycacheFiles = @(Get-ChildItem -LiteralPath $PackagePath -Recurse -File |
    Where-Object { $_.Extension.ToLowerInvariant() -eq ".pyc" -or $_.FullName -like "*\__pycache__\*" })
if ($pycacheFiles.Count -gt 0) {
    $paths = ($pycacheFiles | Select-Object -ExpandProperty FullName) -join [System.Environment]::NewLine
    throw "Python cache files must not be packaged:$([System.Environment]::NewLine)$paths"
}

if ($null -eq $manifest.PSObject.Properties["files"] -or $manifest.files.Count -eq 0) {
    throw "Manifest has no file entries"
}

$manifestPaths = @($manifest.files | ForEach-Object { [string]$_.path })
foreach ($requiredPath in @("version.json", "data/config.json")) {
    if ($manifestPaths -notcontains $requiredPath) {
        throw "Manifest missing required path: $requiredPath"
    }
}

foreach ($requiredQssPath in $RequiredQssPaths) {
    $fullPath = Join-Path $PackagePath $requiredQssPath.Replace("/", "\")
    Assert-FileExists -Path $fullPath
    if ($manifestPaths -notcontains $requiredQssPath) {
        throw "Manifest missing required style resource: $requiredQssPath"
    }
}

foreach ($requiredPluginPath in $RequiredMultimediaPluginPaths) {
    $fullPath = Join-Path $PackagePath $requiredPluginPath.Replace("/", "\")
    Assert-FileExists -Path $fullPath
    if ($manifestPaths -notcontains $requiredPluginPath) {
        throw "Manifest missing required Qt multimedia plugin: $requiredPluginPath"
    }
}

$llamaLibPath = Join-Path $PackagePath "llama_cpp\lib"
if (Test-Path -LiteralPath $llamaLibPath -PathType Container) {
    $duplicateLlamaDlls = @(Get-ChildItem -LiteralPath $llamaLibPath -File -Filter *.dll |
        Where-Object { Test-Path -LiteralPath (Join-Path $PackagePath $_.Name) -PathType Leaf })
    if ($duplicateLlamaDlls.Count -gt 0) {
        $names = ($duplicateLlamaDlls | Select-Object -ExpandProperty Name) -join ", "
        throw "Duplicate llama_cpp runtime DLLs are packaged twice at root and llama_cpp\\lib: $names"
    }
}

$cudaRuntimePackage = $optionalPackages | Where-Object { [string]$_.name -eq "cuda12-runtime" } | Select-Object -First 1
if ($null -ne $cudaRuntimePackage) {
    $packagedCudaDlls = @(
        Get-ChildItem -LiteralPath $PackagePath -File |
            Where-Object { $CudaRuntimeDlls -contains $_.Name.ToLowerInvariant() }
    )
    if ($packagedCudaDlls.Count -gt 0) {
        $names = ($packagedCudaDlls | Select-Object -ExpandProperty Name) -join ", "
        throw "CUDA runtime sidecar is declared, but main package still contains CUDA DLLs at root: $names"
    }
}

Write-Host "Release verification passed."
Write-Host "Version: $($version.version)"
Write-Host "Package: $zipPath"
