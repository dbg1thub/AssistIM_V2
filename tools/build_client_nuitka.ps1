param(
    [string]$Version = "",
    [ValidateSet("test", "stable")]
    [string]$Channel = "test",
    [string]$ServerHost = "",
    [int]$ServerPort = 443,
    [switch]$UseSsl,
    [switch]$EnableConsole,
    [string]$OutputRoot = "dist\client",
    [string]$PythonExe = "python",
    [string]$ConfigTemplate = "deploy\client\config.test.json",
    [ValidateSet("auto", "msvc", "mingw64", "clang")]
    [string]$NuitkaCompiler = "auto",
    [int]$NuitkaJobs = 0,
    [switch]$AssumeYesForDownloads,
    [switch]$SplitCudaRuntime,
    [switch]$SkipNuitka
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptDir "..")
$BuildRoot = Join-Path $RepoRoot $OutputRoot
$NuitkaOutputRoot = Join-Path $BuildRoot "nuitka"
$PackageRoot = Join-Path $BuildRoot "package\AssistIM"
$CudaRuntimeStageRoot = Join-Path $BuildRoot "package-cuda-runtime\AssistIM"
$ReleaseRoot = Join-Path $BuildRoot "release"
$Platform = "win64"
$CudaRuntimeDlls = @("cudart64_12.dll", "cublas64_12.dll", "cublaslt64_12.dll")
$CudaRuntimeZipName = "AssistIM-cuda12-runtime-$Platform.zip"

function Assert-PathInside {
    param(
        [string]$Parent,
        [string]$Child
    )
    $parentFull = [System.IO.Path]::GetFullPath($Parent).TrimEnd('\', '/')
    $childFull = [System.IO.Path]::GetFullPath($Child).TrimEnd('\', '/')
    if (-not ($childFull.Equals($parentFull, [System.StringComparison]::OrdinalIgnoreCase) -or $childFull.StartsWith($parentFull + [System.IO.Path]::DirectorySeparatorChar, [System.StringComparison]::OrdinalIgnoreCase))) {
        throw "Refusing to operate outside build root: $childFull"
    }
}

function Remove-BuildPath {
    param([string]$Path)
    if (Test-Path -LiteralPath $Path) {
        Assert-PathInside -Parent $BuildRoot -Child $Path
        Remove-Item -LiteralPath $Path -Recurse -Force
    }
}

function Get-RelativePath {
    param(
        [string]$BasePath,
        [string]$TargetPath
    )
    $baseFull = [System.IO.Path]::GetFullPath($BasePath).TrimEnd('\', '/') + [System.IO.Path]::DirectorySeparatorChar
    $targetFull = [System.IO.Path]::GetFullPath($TargetPath)
    $baseUri = New-Object System.Uri($baseFull)
    $targetUri = New-Object System.Uri($targetFull)
    return [System.Uri]::UnescapeDataString($baseUri.MakeRelativeUri($targetUri).ToString()).Replace('\', '/')
}

function Copy-DirectoryFiltered {
    param(
        [string]$Source,
        [string]$Destination,
        [string[]]$ExcludedExtensions = @(),
        [string[]]$ExcludedDirectoryNames = @()
    )
    if (-not (Test-Path -LiteralPath $Source)) {
        return
    }
    New-Item -ItemType Directory -Force -Path $Destination | Out-Null
    $sourceFull = [System.IO.Path]::GetFullPath($Source)
    Get-ChildItem -LiteralPath $Source -Recurse -File | ForEach-Object {
        foreach ($directoryName in $ExcludedDirectoryNames) {
            if ($_.FullName -like "*\$directoryName\*") {
                return
            }
        }
        $extension = $_.Extension.ToLowerInvariant()
        if ($ExcludedExtensions -contains $extension) {
            return
        }
        $relativePath = Get-RelativePath -BasePath $sourceFull -TargetPath $_.FullName
        $targetPath = Join-Path $Destination $relativePath
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $targetPath) | Out-Null
        Copy-Item -LiteralPath $_.FullName -Destination $targetPath -Force
    }
}

function Get-PySide6PluginsRoot {
    param([string]$PythonExe)

    $pluginRoot = & $PythonExe -c "from pathlib import Path; import PySide6; print((Path(PySide6.__file__).resolve().parent / 'plugins'))"
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($pluginRoot)) {
        throw "Failed to resolve PySide6 plugins directory via $PythonExe"
    }
    return [string]$pluginRoot
}

function Set-JsonProperty {
    param(
        [object]$Object,
        [string]$Name,
        [object]$Value
    )
    $property = $Object.PSObject.Properties[$Name]
    if ($null -ne $property) {
        $Object.$Name = $Value
    } else {
        $Object | Add-Member -NotePropertyName $Name -NotePropertyValue $Value
    }
}

function Read-VersionFromFile {
    $versionPath = Join-Path $RepoRoot "version.json"
    if (-not (Test-Path -LiteralPath $versionPath)) {
        return "0.1.0"
    }
    $payload = Get-Content -Raw -LiteralPath $versionPath | ConvertFrom-Json
    $versionProperty = $payload.PSObject.Properties["version"]
    if ($null -eq $versionProperty) {
        return "0.1.0"
    }
    $fileVersion = [string]$versionProperty.Value
    if ([string]::IsNullOrWhiteSpace($fileVersion)) {
        return "0.1.0"
    }
    return $fileVersion.TrimStart("v")
}

function Write-JsonFileNoBom {
    param(
        [object]$Payload,
        [string]$Path,
        [int]$Depth = 8
    )
    $json = $Payload | ConvertTo-Json -Depth $Depth
    $encoding = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($Path, $json + [System.Environment]::NewLine, $encoding)
}

function Remove-LlamaCppRootDuplicates {
    param([string]$PackageRoot)

    $llamaLibRoot = Join-Path $PackageRoot "llama_cpp\lib"
    if (-not (Test-Path -LiteralPath $llamaLibRoot -PathType Container)) {
        return @()
    }

    $removed = New-Object System.Collections.Generic.List[object]
    foreach ($dll in Get-ChildItem -LiteralPath $llamaLibRoot -File -Filter *.dll) {
        $rootCopy = Join-Path $PackageRoot $dll.Name
        if (-not (Test-Path -LiteralPath $rootCopy -PathType Leaf)) {
            continue
        }

        $packageHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $dll.FullName).Hash
        $rootHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $rootCopy).Hash
        if ($packageHash -ne $rootHash) {
            continue
        }

        Remove-Item -LiteralPath $rootCopy -Force
        $removed.Add([pscustomobject]@{
            Name = $dll.Name
            SizeMB = [math]::Round(($dll.Length / 1MB), 2)
        }) | Out-Null
    }

    return @($removed.ToArray())
}

function Split-CudaRuntimeFromPackage {
    param(
        [string]$PackageRoot,
        [string]$CudaRuntimeStageRoot,
        [string[]]$RuntimeDllNames
    )

    if (-not $RuntimeDllNames -or $RuntimeDllNames.Count -eq 0) {
        return @()
    }

    New-Item -ItemType Directory -Force -Path $CudaRuntimeStageRoot | Out-Null
    $moved = New-Object System.Collections.Generic.List[object]

    foreach ($dllName in $RuntimeDllNames) {
        $sourcePath = Join-Path $PackageRoot $dllName
        if (-not (Test-Path -LiteralPath $sourcePath -PathType Leaf)) {
            continue
        }

        $targetPath = Join-Path $CudaRuntimeStageRoot $dllName
        Copy-Item -LiteralPath $sourcePath -Destination $targetPath -Force
        Remove-Item -LiteralPath $sourcePath -Force
        $fileInfo = Get-Item -LiteralPath $targetPath
        $moved.Add([pscustomobject]@{
            Name = $dllName
            SizeMB = [math]::Round(($fileInfo.Length / 1MB), 2)
        }) | Out-Null
    }

    return @($moved.ToArray())
}

if ([string]::IsNullOrWhiteSpace($Version)) {
    $Version = Read-VersionFromFile
}
$Version = $Version.TrimStart("v")
$BuildTime = [System.DateTime]::UtcNow.ToString("yyyy-MM-ddTHH:mm:ssZ")
$consoleMode = if ($EnableConsole -or $Channel -eq "test") { "force" } else { "disable" }
$Commit = "unknown"
try {
    $Commit = (& git -C $RepoRoot rev-parse --short HEAD).Trim()
} catch {
    $Commit = "unknown"
}

if ($Channel -eq "test" -and [string]::IsNullOrWhiteSpace($ServerHost)) {
    throw "Test channel builds must specify -ServerHost so the packaged client does not fall back to localhost"
}

New-Item -ItemType Directory -Force -Path $BuildRoot, $NuitkaOutputRoot, $ReleaseRoot | Out-Null
Remove-BuildPath -Path $PackageRoot
Remove-BuildPath -Path $CudaRuntimeStageRoot
New-Item -ItemType Directory -Force -Path $PackageRoot | Out-Null
$staleCudaRuntimeZipPath = Join-Path $ReleaseRoot $CudaRuntimeZipName
if (Test-Path -LiteralPath $staleCudaRuntimeZipPath) {
    Remove-Item -LiteralPath $staleCudaRuntimeZipPath -Force
}

if (-not $SkipNuitka) {
    $entry = Join-Path $RepoRoot "client\main.py"
    $nuitkaArgs = @(
        "-m", "nuitka",
        "--standalone",
        "--enable-plugin=pyside6",
        "--include-package=websockets",
        "--windows-console-mode=$consoleMode",
        "--output-dir=$NuitkaOutputRoot",
        "--output-filename=AssistIM.exe",
        $entry
    )
    if ($AssumeYesForDownloads) {
        $nuitkaArgs += "--assume-yes-for-downloads"
    }
    switch ($NuitkaCompiler) {
        "msvc" {
            $nuitkaArgs += "--msvc=latest"
        }
        "mingw64" {
            $nuitkaArgs += "--mingw64"
        }
        "clang" {
            $nuitkaArgs += "--clang"
        }
    }
    if ($NuitkaJobs -gt 0) {
        $nuitkaArgs += "--jobs=$NuitkaJobs"
    }
    & $PythonExe @nuitkaArgs
    if ($LASTEXITCODE -ne 0) {
        throw "Nuitka build failed with exit code $LASTEXITCODE"
    }
}

$distDir = Get-ChildItem -LiteralPath $NuitkaOutputRoot -Directory -Filter "*.dist" -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1

if ($null -ne $distDir) {
    Copy-Item -Path (Join-Path $distDir.FullName "*") -Destination $PackageRoot -Recurse -Force
} elseif (-not $SkipNuitka) {
    throw "Nuitka output directory was not found under $NuitkaOutputRoot"
}

$removedLlamaDuplicates = Remove-LlamaCppRootDuplicates -PackageRoot $PackageRoot
$splitCudaRuntimeFiles = @()
if ($SplitCudaRuntime) {
    $splitCudaRuntimeFiles = Split-CudaRuntimeFromPackage `
        -PackageRoot $PackageRoot `
        -CudaRuntimeStageRoot $CudaRuntimeStageRoot `
        -RuntimeDllNames $CudaRuntimeDlls
}

$resourcesSource = Join-Path $RepoRoot "client\resources"
$resourcesTarget = Join-Path $PackageRoot "client\resources"
Copy-DirectoryFiltered `
    -Source $resourcesSource `
    -Destination $resourcesTarget `
    -ExcludedExtensions @(".gguf", ".bin", ".safetensors", ".pyc") `
    -ExcludedDirectoryNames @("__pycache__")

$stylesSource = Join-Path $RepoRoot "client\ui\styles\qss"
$stylesTarget = Join-Path $PackageRoot "client\ui\styles\qss"
Copy-DirectoryFiltered `
    -Source $stylesSource `
    -Destination $stylesTarget `
    -ExcludedExtensions @(".pyc") `
    -ExcludedDirectoryNames @("__pycache__")

$pySide6PluginsRoot = Get-PySide6PluginsRoot -PythonExe $PythonExe
$multimediaPluginsSource = Join-Path $pySide6PluginsRoot "multimedia"
$multimediaPluginsTarget = Join-Path $PackageRoot "PySide6\qt-plugins\multimedia"
Copy-DirectoryFiltered `
    -Source $multimediaPluginsSource `
    -Destination $multimediaPluginsTarget `
    -ExcludedExtensions @(".pyc") `
    -ExcludedDirectoryNames @("__pycache__")

$dataTarget = Join-Path $PackageRoot "data"
New-Item -ItemType Directory -Force -Path $dataTarget | Out-Null
$sourceConfigPath = Join-Path $RepoRoot $ConfigTemplate
if (-not (Test-Path -LiteralPath $sourceConfigPath)) {
    $sourceConfigPath = Join-Path $RepoRoot "data\config.json"
}
$targetConfigPath = Join-Path $dataTarget "config.json"

if (Test-Path -LiteralPath $sourceConfigPath) {
    $configPayload = Get-Content -Raw -LiteralPath $sourceConfigPath | ConvertFrom-Json
} else {
    $configPayload = [pscustomobject]@{}
}

if (-not [string]::IsNullOrWhiteSpace($ServerHost)) {
    if ($null -eq $configPayload.PSObject.Properties["Server"]) {
        $configPayload | Add-Member -NotePropertyName "Server" -NotePropertyValue ([pscustomobject]@{})
    }
    Set-JsonProperty -Object $configPayload.Server -Name "Host" -Value $ServerHost
    Set-JsonProperty -Object $configPayload.Server -Name "Port" -Value $ServerPort
    Set-JsonProperty -Object $configPayload.Server -Name "UseSsl" -Value ([bool]$UseSsl)
}

Write-JsonFileNoBom -Payload $configPayload -Path $targetConfigPath -Depth 20

$versionPayload = [ordered]@{
    app = "AssistIM"
    version = $Version
    channel = $Channel
    platform = $Platform
    build_time = $BuildTime
    commit = $Commit
}
Write-JsonFileNoBom -Payload $versionPayload -Path (Join-Path $PackageRoot "version.json") -Depth 5

$manifestPath = Join-Path $PackageRoot "manifest.json"
$files = @()
Get-ChildItem -LiteralPath $PackageRoot -Recurse -File |
    Where-Object { $_.FullName -ne $manifestPath } |
    Sort-Object FullName |
    ForEach-Object {
        $files += [ordered]@{
            path = Get-RelativePath -BasePath $PackageRoot -TargetPath $_.FullName
            size_bytes = $_.Length
            sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $_.FullName).Hash.ToLowerInvariant()
        }
    }

$manifestPayload = [ordered]@{
    app = "AssistIM"
    version = $Version
    channel = $Channel
    platform = $Platform
    generated_at = $BuildTime
    files = $files
}
Write-JsonFileNoBom -Payload $manifestPayload -Path $manifestPath -Depth 8

$zipName = "AssistIM-$Version-$Platform.zip"
$zipPath = Join-Path $ReleaseRoot $zipName
if (Test-Path -LiteralPath $zipPath) {
    Remove-Item -LiteralPath $zipPath -Force
}
Compress-Archive -Path (Join-Path $PackageRoot "*") -DestinationPath $zipPath -Force

$cudaRuntimeZipPath = ""
if ($SplitCudaRuntime -and $splitCudaRuntimeFiles.Count -gt 0) {
    $cudaRuntimeZipPath = Join-Path $ReleaseRoot $cudaRuntimeZipName
    if (Test-Path -LiteralPath $cudaRuntimeZipPath) {
        Remove-Item -LiteralPath $cudaRuntimeZipPath -Force
    }
    Compress-Archive -Path (Join-Path $CudaRuntimeStageRoot "*") -DestinationPath $cudaRuntimeZipPath -Force
}

$latestPayload = [ordered]@{
    app = "AssistIM"
    version = $Version
    channel = $Channel
    platform = $Platform
    package = $zipName
    size_bytes = (Get-Item -LiteralPath $zipPath).Length
    sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $zipPath).Hash.ToLowerInvariant()
    required = $false
    published_at = $BuildTime
}
if ($SplitCudaRuntime -and $splitCudaRuntimeFiles.Count -gt 0) {
    $latestPayload.optional_packages = @(
        [ordered]@{
            name = "cuda12-runtime"
            package = $cudaRuntimeZipName
            size_bytes = (Get-Item -LiteralPath $cudaRuntimeZipPath).Length
            sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $cudaRuntimeZipPath).Hash.ToLowerInvariant()
            required = $false
            install_to = "."
            provides = @(
                "cuda12-runtime",
                "local-gguf-gpu-acceleration"
            )
        }
    )
}
Write-JsonFileNoBom -Payload $latestPayload -Path (Join-Path $ReleaseRoot "latest.json") -Depth 5

Write-Host "Package root: $PackageRoot"
Write-Host "Zip: $zipPath"
Write-Host "Latest manifest: $(Join-Path $ReleaseRoot 'latest.json')"
Write-Host "Console mode: $consoleMode"
Write-Host "Runtime logs: $(Join-Path $PackageRoot 'logs\\assistim.log')"
if ($removedLlamaDuplicates.Count -gt 0) {
    $removedSummary = ($removedLlamaDuplicates | ForEach-Object { "$($_.Name) ($($_.SizeMB) MB)" }) -join ", "
    $removedTotal = [math]::Round((($removedLlamaDuplicates | Measure-Object SizeMB -Sum).Sum), 2)
    Write-Host "Removed duplicate llama_cpp DLLs: $removedSummary"
    Write-Host "Removed duplicate size: $removedTotal MB"
}
if ($SplitCudaRuntime) {
    if ($splitCudaRuntimeFiles.Count -gt 0) {
        $cudaSummary = ($splitCudaRuntimeFiles | ForEach-Object { "$($_.Name) ($($_.SizeMB) MB)" }) -join ", "
        $cudaTotal = [math]::Round((($splitCudaRuntimeFiles | Measure-Object SizeMB -Sum).Sum), 2)
        Write-Host "Split CUDA runtime DLLs: $cudaSummary"
        Write-Host "Split CUDA runtime size: $cudaTotal MB"
        Write-Host "CUDA runtime zip: $cudaRuntimeZipPath"
        Write-Host "Main package now runs without bundled CUDA 12 DLLs and will fall back to CPU unless the sidecar runtime is unpacked."
    } else {
        Write-Host "Split CUDA runtime requested, but no CUDA runtime DLLs were found in package root."
    }
}
Write-Host "Packaged server: $(if ([string]::IsNullOrWhiteSpace($ServerHost)) { 'config default' } else { "$ServerHost`:$ServerPort (ssl=$([bool]$UseSsl))" })"
Write-Host "Nuitka compiler: $NuitkaCompiler"
Write-Host "Nuitka jobs: $(if ($NuitkaJobs -gt 0) { $NuitkaJobs } else { 'default' })"
Write-Host "Assume yes for downloads: $([bool]$AssumeYesForDownloads)"
