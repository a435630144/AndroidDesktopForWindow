# -*- coding: utf-8 -*-
# 便携版打包：PyInstaller onedir + zip
# 用法（pwsh 7）：& 'C:\Users\43563\AppData\Local\Microsoft\WindowsApps\pwsh.exe' -File 'scripts\build_portable.ps1' [-OutName PhoneDesktop_v10]
#   -OutName 输出目录名（默认 PhoneDesktop）。必须传**绝对路径**调用本脚本（坑 #86）。旧 dist 目录若被安全层
#     锁住（bulk-delete 拦截后路径写保护），传新名字即可绕开，旧包原样保留。
param(
    [string]$OutName = 'PhoneDesktop'
)
$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
Write-Host "==> 项目目录: $root"

$py = 'C:\Users\43563\.workbuddy\binaries\python\envs\default\Scripts\python.exe'
if (-not (Test-Path $py)) { throw "找不到 venv python: $py" }

Write-Host "==> PyInstaller 版本:" (& $py -m PyInstaller --version)

$dist = Join-Path $root "dist\$OutName\PhoneDesktop"
$work = Join-Path $root "build\$OutName"

Write-Host "==> 开始打包 (onedir) -> $dist"
# 注意：PyInstaller 6 的 COLLECT 会把产物放到 $distpath\$name\，
# 因此 --distpath 传 dist\$OutName（不含 name），最终 onedir 根即上面的 $dist。
#
# 2026-10-20（DEVLOG 坑 #80 补刀）：PyInstaller 的 INFO 日志走 **stderr**，
# 而本脚本 $ErrorActionPreference='Stop' + 直接 `& $py ...` 会把每条 stderr
# 行变成 NativeCommandError **当场抛错中断打包**（实测 4 秒就"失败"，产物
# 目录都没建）。所以这里：① 临时把偏好降为 Continue；② 用 `*>` 把全部流
# 写进日志文件（不产生错误记录）；③ 退出码之外**再按产物判定**。
$log = Join-Path $work 'build.log'
New-Item -ItemType Directory -Force -Path (Split-Path $log) | Out-Null
$prevEap = $ErrorActionPreference
$ErrorActionPreference = 'Continue'
& $py -m PyInstaller --noconfirm --clean --windowed `
    --name PhoneDesktop `
    --distpath (Join-Path $root "dist\$OutName") `
    --workpath $work `
    --icon assets\app_icon.ico `
    --add-data "assets;assets" `
    --add-data "src/i18n;i18n" `
    --add-data "src/media_smtc.ps1;src" `
    --add-data "src/media_cover.ps1;src" `
    main.py *> $log
$pycode = $LASTEXITCODE
$ErrorActionPreference = $prevEap
Write-Host "==> PyInstaller 退出码 $pycode（日志: $log）"
if ($pycode -ne 0) {
    Write-Host "---- 日志末尾 ----"
    Get-Content $log -Tail 25
    Write-Host "------------------"
}

if (-not (Test-Path $dist)) { throw "找不到输出目录: $dist（PyInstaller exit=$pycode）" }
$exe = Join-Path $dist 'PhoneDesktop.exe'
if (-not (Test-Path $exe)) { throw "找不到主程序: $exe（PyInstaller exit=$pycode）" }

$zipName = if ($OutName -eq 'PhoneDesktop') {
    'PhoneDesktop_Portable.zip'
} else {
    "${OutName}_Portable.zip"
}
$zip = Join-Path $root "dist\$zipName"
if (Test-Path $zip) { Remove-Item $zip -Force }
Compress-Archive -Path $dist -DestinationPath $zip
Write-Host "==> 便携版完成: $zip"
Write-Host "==> 主程序: $exe"
