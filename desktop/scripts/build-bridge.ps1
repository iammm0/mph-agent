# 构建 Python bridge 可执行文件，供 Tauri 安装包内嵌（externalBin）。
# 在项目根目录执行: .\desktop\scripts\build-bridge.ps1
# 或在 desktop 目录执行: ..\..\desktop\scripts\build-bridge.ps1（需先 cd 到项目根再调 pyinstaller）

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$DesktopRoot = Split-Path -Parent $ScriptDir
$ProjectRoot = Split-Path -Parent $DesktopRoot
$BinariesDir = Join-Path $DesktopRoot "src-tauri\binaries"

# 目标三元组（与 Rust 一致，Tauri externalBin 要求）
$TargetTriple = (rustc --print host-tuple 2>$null)
if (-not $TargetTriple) { $TargetTriple = "x86_64-pc-windows-msvc" }
$BridgeName = "mph-agent-bridge-$TargetTriple.exe"

$DistExe = Join-Path $ProjectRoot "dist\mph-agent-bridge.exe"
$DestExe = Join-Path $BinariesDir $BridgeName

Write-Host "Building Python bridge with PyInstaller..."
Push-Location $ProjectRoot
try {
    # Prefer uv run so project deps (jpype1, questionary, etc.) are used
    $useUv = $false
    if (Get-Command uv -ErrorAction SilentlyContinue) {
        uv run python -c "import sys; sys.exit(0)" 2>$null
        if ($LASTEXITCODE -eq 0) { $useUv = $true }
    }
    if ($useUv) {
        Write-Host "Using project env (uv run)..."
        uv pip install pyinstaller --quiet 2>$null
        uv run python -m PyInstaller desktop/scripts/bridge.spec --noconfirm
    } else {
        $py = Get-Command python -ErrorAction SilentlyContinue
        if (-not $py) { $py = Get-Command py -ErrorAction SilentlyContinue }
        if (-not $py) { throw "python or py not found (install uv for project deps: https://docs.astral.sh/uv/)" }
        $pyExe = $py.Source
        & $pyExe -m pip install pyinstaller --quiet
        & $pyExe -m PyInstaller desktop/scripts/bridge.spec --noconfirm
    }
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller exited with code $LASTEXITCODE" }
    if (-not (Test-Path $DistExe)) {
        throw "PyInstaller did not produce: $DistExe"
    }
    New-Item -ItemType Directory -Path $BinariesDir -Force | Out-Null
    Copy-Item -Path $DistExe -Destination $DestExe -Force
    Write-Host "Bridge built: $DestExe"
} finally {
    Pop-Location
}
