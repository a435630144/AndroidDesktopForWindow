# -*- coding: utf-8 -*-
# 便携版打包：PyInstaller onedir + zip
# 用法（pwsh 7）：& 'C:\Users\43563\AppData\Local\Microsoft\WindowsApps\pwsh.exe' -File 'scripts\build_portable.ps1' [-OutName DesktopOrganizerDemo_v2]
#   -OutName 输出目录名（默认 DesktopOrganizerDemo）。旧 dist 目录若被安全层
#     锁住（bulk-delete 拦截后路径写保护），传新名字即可绕开，旧包原样保留。
param(
    [string]$OutName = 'DesktopOrganizerDemo'
)
$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
Write-Host "==> 项目目录: $root"

$py = 'C:\Users\43563\.workbuddy\binaries\python\envs\default\Scripts\python.exe'
if (-not (Test-Path $py)) { throw "找不到 venv python: $py" }

Write-Host "==> PyInstaller 版本:" (& $py -m PyInstaller --version)

$dist = Join-Path $root "dist\$OutName\DesktopOrganizerDemo"
$work = Join-Path $root "build\$OutName\DesktopOrganizerDemo"

Write-Host "==> 开始打包 (onedir) -> $dist"
& $py -m PyInstaller --noconfirm --clean --windowed `
    --name DesktopOrganizerDemo `
    --distpath $dist `
    --workpath $work `
    --icon assets\app_icon.ico `
    --add-data "assets;assets" `
    main.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller 打包失败 (exit=$LASTEXITCODE)" }

if (-not (Test-Path $dist)) { throw "找不到输出目录: $dist" }
$exe = Join-Path $dist 'DesktopOrganizerDemo.exe'
if (-not (Test-Path $exe)) { throw "找不到主程序: $exe" }

$zipName = if ($OutName -eq 'DesktopOrganizerDemo') {
    'DesktopOrganizerDemo_Portable.zip'
} else {
    "${OutName}_Portable.zip"
}
$zip = Join-Path $root "dist\$zipName"
if (Test-Path $zip) { Remove-Item $zip -Force }
Compress-Archive -Path $dist -DestinationPath $zip
Write-Host "==> 便携版完成: $zip"
Write-Host "==> 主程序: $exe"
