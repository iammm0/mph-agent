# 下载 Adoptium JDK 11 (Windows x64) 并解压到 src-tauri/resources/runtime/java，供 Tauri 打包进安装程序。
# 在 desktop 目录下执行: .\scripts\download-jdk11.ps1
# CI 中在 desktop 目录执行即可。

$ErrorActionPreference = "Stop"
$AdoptiumUrl = "https://api.adoptium.net/v3/binary/latest/11/ga/windows/x64/jdk/hotspot/normal/eclipse?project=jdk&archive_type=zip"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$DesktopRoot = Split-Path -Parent $ScriptDir
$TargetDir = Join-Path $DesktopRoot "src-tauri\resources\runtime\java"
$TempZip = [System.IO.Path]::GetTempFileName() + ".zip"
$TempExtract = Join-Path $env:TEMP "mph-agent-jdk11-extract"

if (Test-Path (Join-Path $TargetDir "bin\java.exe")) {
    Write-Host "JDK 11 already present at $TargetDir, skip download."
    exit 0
}

Write-Host "Downloading JDK 11 from Adoptium..."
try {
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    Invoke-WebRequest -Uri $AdoptiumUrl -OutFile $TempZip -UseBasicParsing -UserAgent "mph-agent"
} catch {
    Write-Error "Download failed: $_"
    exit 1
}

Write-Host "Extracting..."
if (Test-Path $TempExtract) { Remove-Item -Recurse -Force $TempExtract }
Expand-Archive -Path $TempZip -DestinationPath $TempExtract -Force
Remove-Item $TempZip -Force -ErrorAction SilentlyContinue

$topLevel = Get-ChildItem -Path $TempExtract -Directory
if ($topLevel.Count -ne 1) {
    Write-Error "Unexpected archive structure: expected one top-level directory."
    exit 1
}
$jdkRoot = $topLevel[0].FullName

New-Item -ItemType Directory -Path $TargetDir -Force | Out-Null
Get-ChildItem -Path $jdkRoot | ForEach-Object {
    $dest = Join-Path $TargetDir $_.Name
    if (Test-Path $dest) { Remove-Item -Recurse -Force $dest }
    Move-Item -Path $_.FullName -Destination $dest -Force
}

Remove-Item -Recurse -Force $TempExtract -ErrorAction SilentlyContinue

if (-not (Test-Path (Join-Path $TargetDir "bin\java.exe"))) {
    Write-Error "After extract, bin\java.exe not found under $TargetDir"
    exit 1
}
Write-Host "JDK 11 ready at $TargetDir"
