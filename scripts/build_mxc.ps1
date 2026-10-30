#requires -Version 7.0
[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [ValidateSet('x64', 'arm64')]
    [string]$Architecture,

    [Parameter(Mandatory)]
    [string]$UpstreamDirectory,

    [string]$OutputDirectory
)

$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $false
if (-not $IsWindows) { throw 'Build this executor on Windows with MSVC and the Windows SDK.' }

$labRoot = Split-Path -Parent $PSScriptRoot
$upstreamRoot = (Resolve-Path -LiteralPath $UpstreamDirectory).Path
$upstreamLockPath = Join-Path $labRoot 'upstream.lock.json'
$upstreamLock = Get-Content -LiteralPath $upstreamLockPath -Raw | ConvertFrom-Json
$target = @{ x64 = 'x86_64-pc-windows-msvc'; arm64 = 'aarch64-pc-windows-msvc' }[$Architecture]
if (-not $OutputDirectory) { $OutputDirectory = Join-Path $labRoot "artifacts/mxc-windows-$Architecture" }
$outputRoot = [IO.Path]::GetFullPath($OutputDirectory)
if (Test-Path -LiteralPath $outputRoot) { throw "Build evidence already exists: $outputRoot" }
[void](New-Item -ItemType Directory -Path $outputRoot)

function Invoke-CheckedText {
    param([string]$Executable, [string[]]$Arguments)
    $lines = & $Executable @Arguments 2>&1
    $commandExit = $LASTEXITCODE
    if ($commandExit -ne 0) { throw "$Executable exited $commandExit`: $($lines -join "`n")" }
    ($lines -join "`n").Trim()
}

function Get-FileReceipt {
    param([string]$Path)
    $item = Get-Item -LiteralPath $Path
    [ordered]@{
        name = $item.Name
        bytes = $item.Length
        sha256 = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
    }
}

function Find-Dumpbin {
    $available = Get-Command dumpbin.exe -ErrorAction SilentlyContinue
    if ($available) { return $available.Source }
    $vswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio/Installer/vswhere.exe'
    if (-not (Test-Path -LiteralPath $vswhere)) { return $null }
    $installPath = & $vswhere -latest -products '*' -property installationPath
    if ($LASTEXITCODE -ne 0 -or -not $installPath) { return $null }
    $toolsRoot = Join-Path ($installPath | Select-Object -First 1) 'VC/Tools/MSVC'
    if (-not (Test-Path -LiteralPath $toolsRoot)) { return $null }
    $hostFolder = if ([Runtime.InteropServices.RuntimeInformation]::OSArchitecture -eq 'Arm64') { 'Hostarm64' } else { 'Hostx64' }
    foreach ($toolset in (Get-ChildItem -LiteralPath $toolsRoot -Directory | Sort-Object Name -Descending)) {
        foreach ($hostName in @($hostFolder, 'Hostx64')) {
            $candidate = Join-Path $toolset.FullName "bin/$hostName/$Architecture/dumpbin.exe"
            if (Test-Path -LiteralPath $candidate) { return $candidate }
        }
    }
    $null
}

$cargoArguments = @(
    '+1.93', '--config', '../.azure-pipelines/.cargo/config.public.toml',
    'build', '--locked', '--release', '-p', 'wxc', '--bin', 'wxc-exec',
    '--target', $target, '--no-default-features', '--color', 'never'
)
$receipt = [ordered]@{
    schema_version = 1
    status = 'building'
    confinement_status = 'not_tested'
    started_at = [DateTimeOffset]::UtcNow.ToString('o')
    architecture = $Architecture
    target = $target
    upstream_repository = $upstreamLock.repository
    expected_upstream_revision = $upstreamLock.revision
    upstream_lock = Get-FileReceipt $upstreamLockPath
    command = [ordered]@{ executable = 'cargo'; arguments = $cargoArguments; working_directory = 'upstream/src' }
    build_exit_code = $null
    runner = [ordered]@{
        os = $env:RUNNER_OS
        architecture = $env:RUNNER_ARCH
        image_os = $env:ImageOS
        image_version = $env:ImageVersion
        windows_version = [Environment]::OSVersion.VersionString
    }
    workflow = [ordered]@{
        repository = $env:GITHUB_REPOSITORY
        revision = $env:GITHUB_SHA
        run_id = $env:GITHUB_RUN_ID
        run_attempt = $env:GITHUB_RUN_ATTEMPT
        workflow_ref = $env:GITHUB_WORKFLOW_REF
    }
    files = @()
}

try {
    foreach ($overrideName in @('RUSTFLAGS', 'CARGO_ENCODED_RUSTFLAGS', 'CARGO_BUILD_RUSTFLAGS', "CARGO_TARGET_$($target.ToUpperInvariant().Replace('-', '_'))_RUSTFLAGS")) {
        if ($null -ne [Environment]::GetEnvironmentVariable($overrideName)) {
            throw "$overrideName is set; remove the override to preserve upstream compiler flags."
        }
    }
    if ([Environment]::GetEnvironmentVariable('CARGO_TARGET_DIR')) {
        throw 'CARGO_TARGET_DIR is set; use the upstream target directory for this recorded build.'
    }
    $revision = Invoke-CheckedText git @('-C', $upstreamRoot, 'rev-parse', 'HEAD')
    if ($revision -ne $upstreamLock.revision) { throw "MXC revision differs from upstream.lock.json: $revision" }
    $upstreamStatus = Invoke-CheckedText git @('-C', $upstreamRoot, '--no-optional-locks', 'status', '--porcelain')
    if ($upstreamStatus) { throw "MXC checkout is dirty: $upstreamStatus" }
    $receipt.upstream_revision = $revision
    $receipt.upstream_clean_before = $true
    $receipt.lab_revision = Invoke-CheckedText git @('-C', $labRoot, 'rev-parse', 'HEAD')
    $receipt.cargo_lock = Get-FileReceipt (Join-Path $upstreamRoot 'src/Cargo.lock')
    $receipt.compiler_config = Get-FileReceipt (Join-Path $upstreamRoot '.cargo/config.toml')
    $receipt.dependency_feed_config = Get-FileReceipt (Join-Path $upstreamRoot '.azure-pipelines/.cargo/config.public.toml')
    Copy-Item -LiteralPath (Join-Path $upstreamRoot 'LICENSE.md') -Destination (Join-Path $outputRoot 'LICENSE.md')

    Push-Location (Join-Path $upstreamRoot 'src')
    try {
        $receipt.rustc = Invoke-CheckedText rustc @('+1.93', '-Vv')
        $receipt.cargo = Invoke-CheckedText cargo @('+1.93', '-V')
        & cargo @cargoArguments 2>&1 | Tee-Object -FilePath (Join-Path $outputRoot 'build.log')
        $receipt.build_exit_code = $LASTEXITCODE
        if ($receipt.build_exit_code -ne 0) { throw "MXC build failed with exit code $($receipt.build_exit_code)." }
    }
    finally { Pop-Location }

    $upstreamStatus = Invoke-CheckedText git @('-C', $upstreamRoot, '--no-optional-locks', 'status', '--porcelain')
    $receipt.upstream_clean_after = -not [bool]$upstreamStatus
    if ($upstreamStatus) { throw "MXC build modified tracked or untracked source: $upstreamStatus" }
    $builtExecutable = Join-Path $upstreamRoot "src/target/$target/release/wxc-exec.exe"
    $bundleExecutable = Join-Path $outputRoot 'wxc-exec.exe'
    Copy-Item -LiteralPath $builtExecutable -Destination $bundleExecutable
    $receipt.product_version = (Get-Item -LiteralPath $bundleExecutable).VersionInfo.ProductVersion

    $dumpbin = Find-Dumpbin
    if ($dumpbin) {
        $imports = & $dumpbin /nologo /imports $bundleExecutable 2>&1
        $dumpbinExit = $LASTEXITCODE
        $imports | Set-Content -LiteralPath (Join-Path $outputRoot 'pe-imports.txt') -Encoding utf8
        $receipt.pe_imports = [ordered]@{ status = if ($dumpbinExit -eq 0) { 'recorded' } else { 'failed' }; tool = $dumpbin; exit_code = $dumpbinExit }
        if ($dumpbinExit -ne 0) { throw "dumpbin failed with exit code $dumpbinExit." }
    }
    else { $receipt.pe_imports = [ordered]@{ status = 'not_recorded'; reason = 'dumpbin.exe was not found' } }
    $receipt.status = 'built'
}
catch {
    $receipt.status = 'failed'
    $receipt.error = $_.Exception.Message
    throw
}
finally {
    $receipt.finished_at = [DateTimeOffset]::UtcNow.ToString('o')
    $receipt.files = @(Get-ChildItem -LiteralPath $outputRoot -File | Sort-Object Name | ForEach-Object { Get-FileReceipt $_.FullName })
    $receipt | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $outputRoot 'manifest.json') -Encoding utf8
}
