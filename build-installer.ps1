# One-click build installer (Windows):
# - Python bridge exe (PyInstaller)
# - Desktop app (Tauri + React)
# - Bundled Java 11 runtime
#
# Run in project root:
#   .\build-installer.ps1
#
# Output installers:
#   desktop\src-tauri\target\release\bundle\

#requires -Version 5.1

$ErrorActionPreference = "Stop"

# Ensure UTF-8 output on Windows PowerShell
try {
    [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
    $OutputEncoding = [System.Text.Encoding]::UTF8
} catch {}

$ProjectRoot = $PSScriptRoot
if (-not $ProjectRoot) { $ProjectRoot = (Get-Location).Path }

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  mph-agent installer build (all-in-one)" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# 1. 构建 Python 桥接层 exe（PyInstaller 打包 agent + bridge_entry）
Write-Host "[1/3] Build bridge exe (PyInstaller)..." -ForegroundColor Yellow
& "$ProjectRoot\desktop\scripts\build-bridge.ps1"
if ($LASTEXITCODE -ne 0) {
    Write-Error "Bridge build failed. Exit code: $LASTEXITCODE"
    exit $LASTEXITCODE
}
Write-Host "  OK: desktop\src-tauri\binaries\mph-agent-bridge-*.exe" -ForegroundColor Green
Write-Host ""

# 2. Copy local Java 11 into Tauri resources (no remote download)
Write-Host "[2/3] Prepare bundled Java 11 (runtime/java)..." -ForegroundColor Yellow
$srcJava = Join-Path $ProjectRoot ".venv\java11"
$dstJava = Join-Path $ProjectRoot "desktop\src-tauri\resources\runtime\java"

if (Test-Path -LiteralPath (Join-Path $dstJava "bin\java.exe")) {
    Write-Host "  OK: runtime/java already present, skip copy." -ForegroundColor Green
} else {
    if (-not (Test-Path -LiteralPath (Join-Path $srcJava "bin\java.exe"))) {
        throw "Local JDK 11 not found at: $srcJava (expected bin\java.exe)"
    }

    New-Item -ItemType Directory -Path $dstJava -Force | Out-Null
    # Clean destination except .gitkeep
    Get-ChildItem -LiteralPath $dstJava -Force -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -ne ".gitkeep" } |
        ForEach-Object { Remove-Item -LiteralPath $_.FullName -Recurse -Force -ErrorAction SilentlyContinue }

    $robocopy = Get-Command robocopy -ErrorAction SilentlyContinue
    if ($robocopy) {
        # robocopy exit codes: 0-7 success, >=8 failure
        robocopy $srcJava $dstJava /E /NFL /NDL /NJH /NJS /NP /R:1 /W:1 | Out-Null
        if ($LASTEXITCODE -ge 8) {
            throw "Failed to copy JDK 11 with robocopy. Exit code: $LASTEXITCODE"
        }
    } else {
        Copy-Item -LiteralPath (Join-Path $srcJava "*") -Destination $dstJava -Recurse -Force
    }

    if (-not (Test-Path -LiteralPath (Join-Path $dstJava "bin\java.exe"))) {
        throw "After copy, bin\java.exe not found under: $dstJava"
    }
    Write-Host "  OK: desktop\src-tauri\resources\runtime\java" -ForegroundColor Green
}
Write-Host ""

# 3. 构建 Tauri 桌面端（前端 + 打包进 exe/java 的安装程序）
Write-Host "[3/3] Build desktop app & installers (Tauri)..." -ForegroundColor Yellow
Push-Location "$ProjectRoot\desktop"
try {
    npm run tauri build
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Tauri build failed. Exit code: $LASTEXITCODE"
        exit $LASTEXITCODE
    }
} finally {
    Pop-Location
}

$bundleDir = Join-Path $ProjectRoot "desktop\src-tauri\target\release\bundle"
Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host "  Build done" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host "Installer output: $bundleDir"
if (Test-Path $bundleDir) {
    Get-ChildItem $bundleDir -Recurse -File | Where-Object { $_.Extension -match '\.(exe|msi)$' } | ForEach-Object {
        $sizeMb = [math]::Round($_.Length / 1MB, 2)
        $relative = $_.FullName.Substring($bundleDir.Length).TrimStart([char]92, [char]47)
        Write-Host ("  - {0} ({1} MB)" -f $relative, $sizeMb) -ForegroundColor Cyan
    }
}
Write-Host ""
Write-Host "Installer contains:" -ForegroundColor White
Write-Host "  - Python bridge exe (mph-agent-bridge)" -ForegroundColor White
Write-Host "  - Desktop app (Tauri + React)" -ForegroundColor White
Write-Host "  - Bundled Java 11 runtime (resources/runtime/java)" -ForegroundColor White
Write-Host ""
