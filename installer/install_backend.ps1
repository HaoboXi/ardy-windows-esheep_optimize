param([string]$InstallRoot = (Join-Path $env:LOCALAPPDATA 'ARDYMotionBridge\runtime'), [string]$BootstrapPython, [string]$Descriptor, [string]$Mode='install')
$ErrorActionPreference='Stop'
if (-not $BootstrapPython) {
    $candidate=(Get-Command python.exe -ErrorAction SilentlyContinue).Source
    if ($candidate -and $candidate -notlike '*WindowsApps*') { $BootstrapPython=$candidate }
}
if (-not $BootstrapPython) {
    $blenderRoots=@()
    foreach ($programRoot in @($env:ProgramFiles,${env:ProgramFiles(x86)})) {
        if ($programRoot) { $blenderRoots+=Get-ChildItem -Path (Join-Path $programRoot 'Blender Foundation\Blender*') -Directory -ErrorAction SilentlyContinue | Select-Object -ExpandProperty FullName }
    }
    foreach ($registryRoot in @('HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*','HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*')) {
        foreach ($entry in (Get-ItemProperty -Path $registryRoot -ErrorAction SilentlyContinue | Where-Object {$_.DisplayName -like 'Blender*'})) {
            if ($entry.InstallLocation) { $blenderRoots+=$entry.InstallLocation }
        }
    }
    foreach ($blenderRoot in $blenderRoots) {
        $candidate=Get-ChildItem -Path (Join-Path $blenderRoot '*\python\bin\python.exe') -File -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty FullName
        if ($candidate) { $BootstrapPython=$candidate; break }
    }
}
if (-not $BootstrapPython) { throw 'Use Blender Install AI Environment (it supplies bundled Python), or provide -BootstrapPython. An ARDY/Conda environment is not required.' }
$sourceRoot=Split-Path -Parent $PSScriptRoot
if (-not $Descriptor) { $Descriptor=Join-Path $sourceRoot 'config\deployment_descriptor.json' }
if (-not (Test-Path -LiteralPath $Descriptor)) {
    # Source ZIPs omit the external archive descriptor to avoid a self-hash cycle.
    # Local code/model inventories are pinned by the ZIP's source manifest.
    $manifestPath=Join-Path $sourceRoot 'config\release_manifest.json'
    if (-not (Test-Path -LiteralPath $manifestPath)) { throw 'The matching source/deployment manifest is missing. Use the complete release.' }
    $sourceManifest=Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $sources=Get-Content -LiteralPath (Join-Path $sourceRoot 'config\model_sources.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    $runtimeWheels=@(Get-Content -LiteralPath (Join-Path $sourceRoot 'config\wheels.json') -Raw -Encoding UTF8 | ConvertFrom-Json)
    $translationWheels=@(Get-Content -LiteralPath (Join-Path $sourceRoot 'config\translation_wheels.json') -Raw -Encoding UTF8 | ConvertFrom-Json)
    $condaPackages=@(Get-Content -LiteralPath (Join-Path $sourceRoot 'config\conda_packages.json') -Raw -Encoding UTF8 | ConvertFrom-Json)
    New-Item -ItemType Directory -Force -Path $InstallRoot | Out-Null
    $Descriptor=Join-Path $InstallRoot '.ardy-bootstrap-descriptor.json'
    $bootstrap=@{schema='ardy.deployment.v1';version=$sourceManifest.version;backend_manifest_sha256=(Get-FileHash -LiteralPath $manifestPath -Algorithm SHA256).Hash.ToLowerInvariant();model_sources=$sources;conda_packages=$condaPackages;runtime_wheels=$runtimeWheels;translation_wheels=$translationWheels;backend_archive=@{bytes=0};known_download_bytes=0}
    $bootstrap | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $Descriptor -Encoding UTF8
}
$arguments=@('-I',(Join-Path $PSScriptRoot 'install_backend.py'),'--install-root',$InstallRoot,'--descriptor',$Descriptor,'--mode',$Mode)
if (Test-Path -LiteralPath (Join-Path $sourceRoot 'ardy\model\ardy_model.py')) { $arguments+=@('--backend-source',$sourceRoot) }
$env:PYTHONUTF8='1'
& $BootstrapPython @arguments
if ($LASTEXITCODE -ne 0) { throw "ARDY installation failed ($LASTEXITCODE). See install.log in the selected directory." }
