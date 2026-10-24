# PhoneDesktop media sidecar (SMTC reader).
#
# Usage:
#   powershell -NoProfile -ExecutionPolicy Bypass -File media_smtc.ps1 <cmd.json> <interval_ms>
#
# Protocol (one line per sample, ASCII safe):
#   B64:<base64 of UTF-8 JSON>
# JSON keys: ok, has, title, artist, album, playing, pos, dur, app
#
# This file is intentionally ASCII-only: Windows PowerShell 5.1 reads .ps1
# files using the ANSI code page unless they carry a UTF-8 BOM, so any
# non-ASCII literal here could be mangled on a non-Chinese system.
# All text that reaches the UI is produced at runtime (song titles etc.),
# encoded as base64 to survive the redirected-stdout code page.

$ErrorActionPreference = 'Continue'

$cmdPath = $null
$interval = 1200
if ($args.Count -ge 1) { $cmdPath = [string]$args[0] }
if ($args.Count -ge 2) { $interval = [int]$args[1] }
if ($interval -lt 300) { $interval = 300 }

function Emit([hashtable]$obj) {
    try {
        $json = $obj | ConvertTo-Json -Compress -Depth 4
        $bytes = [System.Text.Encoding]::UTF8.GetBytes($json)
        $b64 = [Convert]::ToBase64String($bytes)
        [Console]::Out.WriteLine('B64:' + $b64)
        [Console]::Out.Flush()
    } catch {
        # never let output formatting kill the loop
    }
}

# ---- async helper (WinRT IAsyncOperation -> .NET Task) ----
$script:asTaskGeneric = $null
try {
    Add-Type -AssemblyName System.Runtime.WindowsRuntime | Out-Null
    $script:asTaskGeneric = ([System.WindowsRuntimeSystemExtensions].GetMethods() |
        Where-Object {
            $_.Name -eq 'AsTask' -and
            $_.GetParameters().Count -eq 1 -and
            $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1'
        })[0]
    if ($null -eq $script:asTaskGeneric) { throw 'AsTask not found' }
} catch {
    Emit @{ ok = $false; err = 'winrt-runtime' }
    exit 1
}

function Await($op, $type) {
    $m = $script:asTaskGeneric.MakeGenericMethod($type)
    $t = $m.Invoke($null, @($op))
    $t.Wait(-1) | Out-Null
    return $t.Result
}

# ---- manager ----
$script:manager = $null
try {
    $mgrType = [Windows.Media.Control.GlobalSystemMediaTransportControlsSessionManager, Windows.Media.Control, ContentType = WindowsRuntime]
    $script:manager = Await ($mgrType::RequestAsync()) ([Windows.Media.Control.GlobalSystemMediaTransportControlsSessionManager])
} catch {
    Emit @{ ok = $false; err = 'manager' }
    exit 2
}
if ($null -eq $script:manager) {
    Emit @{ ok = $false; err = 'manager-null' }
    exit 2
}

$propsType = [Windows.Media.Control.GlobalSystemMediaTransportControlsSessionMediaProperties]
$script:lastSeq = -1
$script:lastCmdWrite = [DateTime]::MinValue

function Pick-Session {
    $s = $null
    try { $s = $script:manager.GetCurrentSession() } catch { $s = $null }
    if ($null -ne $s) { return $s }
    try {
        $all = $script:manager.GetSessions()
        foreach ($cand in $all) {
            try {
                $info = $cand.GetPlaybackInfo()
                if ($null -ne $info -and $info.PlaybackStatus.ToString() -eq 'Playing') {
                    return $cand
                }
            } catch { }
        }
        foreach ($cand in $all) {
            if ($null -ne $cand) { return $cand }
        }
    } catch { }
    return $null
}

while ($true) {
    $session = $null
    try { $session = Pick-Session } catch { $session = $null }

    if ($null -eq $session) {
        Emit @{ ok = $true; has = $false }
    } else {
        try {
            $title = ''
            $artist = ''
            $album = ''
            try {
                $p = Await ($session.TryGetMediaPropertiesAsync()) $propsType
                if ($null -ne $p) {
                    if ($null -ne $p.Title) { $title = [string]$p.Title }
                    if ($null -ne $p.Artist) { $artist = [string]$p.Artist }
                    if ($null -ne $p.AlbumTitle) { $album = [string]$p.AlbumTitle }
                }
            } catch { }
            $pos = 0.0
            $dur = 0.0
            try {
                $tl = $session.GetTimelineProperties()
                if ($null -ne $tl) {
                    $pos = [math]::Round($tl.Position.TotalSeconds, 2)
                    $dur = [math]::Round($tl.EndTime.TotalSeconds, 2)
                }
            } catch { }
            $playing = $false
            try {
                $pi = $session.GetPlaybackInfo()
                if ($null -ne $pi) {
                    $playing = ($pi.PlaybackStatus.ToString() -eq 'Playing')
                }
            } catch { }
            $app = ''
            try { $app = [string]$session.SourceAppUserModelId } catch { }
            if ([string]::IsNullOrWhiteSpace($title)) {
                Emit @{ ok = $true; has = $false }
            } else {
                Emit @{
                    ok = $true; has = $true; title = $title; artist = $artist
                    album = $album; playing = $playing
                    pos = $pos; dur = $dur; app = $app
                }
            }
        } catch {
            Emit @{ ok = $true; has = $false }
        }
    }

    # ---- command channel (file based; no stdin plumbing needed) ----
    if ($cmdPath) {
        try {
            if (Test-Path -LiteralPath $cmdPath) {
                $write = (Get-Item -LiteralPath $cmdPath).LastWriteTime
                if ($write -gt $script:lastCmdWrite) {
                    $script:lastCmdWrite = $write
                    $raw = Get-Content -LiteralPath $cmdPath -Raw -ErrorAction Stop
                    if ($raw) {
                        $cmd = $raw | ConvertFrom-Json
                        $seq = [int]$cmd.seq
                        if ($seq -ne $script:lastSeq) {
                            $script:lastSeq = $seq
                            if ($cmd.cmd -eq 'seek' -and $null -ne $session) {
                                try {
                                    $ticks = [int64]([double]$cmd.value * 10000000.0)
                                    $op = $session.TryChangePlaybackPositionAsync($ticks)
                                    # fire and forget: do not Await here (a slow
                                    # player would stall the sampling loop)
                                    if ($null -eq $op) { }
                                } catch { }
                            }
                        }
                    }
                }
            }
        } catch { }
    }

    Start-Sleep -Milliseconds $interval
}
