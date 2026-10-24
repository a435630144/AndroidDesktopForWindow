# PhoneDesktop cover reader (SMTC thumbnail -> bytes).
#
# Dot-source this file, then call:
#   $bytes = Get-CoverBytes $props.Thumbnail      # byte[] or $null
#
# Why this file exists (2026-10-24, measured):
#   PowerShell 5.1 cannot project a WinRT *interface* result. The object
#   returned by `$thumbnail.OpenReadAsync()` is a bare `System.__ComObject`:
#   `.Size` silently reads as 0 and casting it to `IInputStream` throws
#   ("cannot convert System.__ComObject to Windows.Storage.Streams.IInputStream").
#   The workaround is to copy that unreadable source stream into an
#   `InMemoryRandomAccessStream` -- a WinRT *class*, which PowerShell projects
#   properly -- and read the copy with `DataReader`.
#
#   `RandomAccessStream.CopyAsync(IInputStream, IOutputStream)` is invoked by
#   reflection because the two-argument static overload is not exposed through
#   PowerShell's method binder. The destination must be cast to `IOutputStream`
#   first, otherwise PowerShell passes its PSObject wrapper instead.
#
# ASCII-only on purpose: Windows PowerShell 5.1 reads .ps1 files with the ANSI
# code page unless they carry a UTF-8 BOM.

Add-Type -AssemblyName System.Runtime.WindowsRuntime | Out-Null

# Make the WinRT type literals resolvable by name.
[Windows.Storage.Streams.InMemoryRandomAccessStream, Windows.Storage.Streams, ContentType = WindowsRuntime] | Out-Null
[Windows.Storage.Streams.RandomAccessStream, Windows.Storage.Streams, ContentType = WindowsRuntime] | Out-Null
[Windows.Storage.Streams.DataReader, Windows.Storage.Streams, ContentType = WindowsRuntime] | Out-Null
[Windows.Storage.Streams.IRandomAccessStreamWithContentType, Windows.Storage.Streams, ContentType = WindowsRuntime] | Out-Null
[Windows.Storage.Streams.IInputStream, Windows.Storage.Streams, ContentType = WindowsRuntime] | Out-Null
[Windows.Storage.Streams.IOutputStream, Windows.Storage.Streams, ContentType = WindowsRuntime] | Out-Null

$script:coverAsTask = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
    $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and
    $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]

$script:coverAsTaskProgress = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
    $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and
    $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperationWithProgress`2' })[0]

$script:coverCopyAsync = $null

function Invoke-CoverAwait($operation, $resultType) {
    $m = $script:coverAsTask.MakeGenericMethod($resultType)
    $t = $m.Invoke($null, @($operation))
    $t.Wait(-1) | Out-Null
    return $t.Result
}

function Get-CoverBytes($thumbnail) {
    # Returns the image bytes published by the player, or $null when the
    # session has no artwork / the stream cannot be read.
    if ($null -eq $thumbnail) { return $null }
    $dest = $null
    $reader = $null
    try {
        $src = Invoke-CoverAwait ($thumbnail.OpenReadAsync()) ([Windows.Storage.Streams.IRandomAccessStreamWithContentType])
        if ($null -eq $src) { return $null }

        $dest = [Windows.Storage.Streams.InMemoryRandomAccessStream]::new()
        if ($null -eq $dest) { return $null }

        if ($null -eq $script:coverCopyAsync) {
            $script:coverCopyAsync = [Windows.Storage.Streams.RandomAccessStream].GetMethod(
                'CopyAsync',
                [Type[]]@([Windows.Storage.Streams.IInputStream],
                          [Windows.Storage.Streams.IOutputStream]))
        }
        if ($null -eq $script:coverCopyAsync) { return $null }

        $copyArgs = New-Object 'object[]' 2
        $copyArgs[0] = $src
        $copyArgs[1] = [Windows.Storage.Streams.IOutputStream]$dest
        $copyOp = $script:coverCopyAsync.Invoke($null, $copyArgs)
        if ($null -eq $copyOp) { return $null }
        $copyTask = $script:coverAsTaskProgress.MakeGenericMethod(
            [uint64], [uint64]).Invoke($null, @($copyOp))
        $copyTask.Wait(-1) | Out-Null

        $null = $dest.Seek(0)
        $size = [int]$dest.Size
        # 8 MB guard: album art is tens of KB; a huge value means we are
        # reading something that is not an image.
        if ($size -le 16 -or $size -gt 8388608) { return $null }

        $reader = [Windows.Storage.Streams.DataReader]::new($dest)
        Invoke-CoverAwait ($reader.LoadAsync([uint32]$size)) ([uint32]) | Out-Null
        $bytes = New-Object 'System.Byte[]' $size
        $reader.ReadBytes($bytes)
        return $bytes
    } catch {
        return $null
    } finally {
        if ($null -ne $reader) { try { $reader.Dispose() } catch { } }
        if ($null -ne $dest) { try { $dest.Dispose() } catch { } }
    }
}
