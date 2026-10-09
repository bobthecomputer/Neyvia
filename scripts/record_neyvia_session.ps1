param(
    [ValidateRange(5, 7200)]
    [int]$DurationSeconds = 180,
    [ValidateRange(1, 60)]
    [int]$FrameEverySeconds = 5,
    [string]$WindowTitle = "Neyvia - Intelligence Aligned",
    [string]$OutputDirectory = "output/ui-proof-latest"
)

$ErrorActionPreference = "Stop"

function Resolve-RequiredCommand {
    param([Parameter(Mandatory = $true)][string]$Name)
    $command = Get-Command $Name -ErrorAction SilentlyContinue
    if (-not $command) {
        throw "$Name is required but was not found on PATH."
    }
    return $command.Source
}

$workspaceRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$resolvedOutput = if ([System.IO.Path]::IsPathRooted($OutputDirectory)) {
    [System.IO.Path]::GetFullPath($OutputDirectory)
} else {
    [System.IO.Path]::GetFullPath((Join-Path $workspaceRoot $OutputDirectory))
}

[System.IO.Directory]::CreateDirectory($resolvedOutput) | Out-Null
$ffmpeg = Resolve-RequiredCommand -Name "ffmpeg"
$ffprobe = Resolve-RequiredCommand -Name "ffprobe"
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$videoPath = Join-Path $resolvedOutput "neyvia-session-$stamp.mp4"
$framesDirectory = Join-Path $resolvedOutput "neyvia-session-$stamp-frames"
$receiptPath = Join-Path $resolvedOutput "neyvia-session-$stamp-receipt.json"
[System.IO.Directory]::CreateDirectory($framesDirectory) | Out-Null

Write-Host "Recording only the Neyvia app window for $DurationSeconds seconds..."
Write-Host "Window title: $WindowTitle"

$captureInput = "title=$WindowTitle"
$recordArguments = @(
    "-hide_banner", "-loglevel", "warning", "-y",
    "-f", "gdigrab", "-framerate", "30", "-i", $captureInput,
    "-t", $DurationSeconds,
    "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2",
    "-c:v", "libx264", "-preset", "veryfast", "-crf", "19",
    "-pix_fmt", "yuv420p", "-movflags", "+faststart",
    $videoPath
)

& $ffmpeg @recordArguments
if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $videoPath)) {
    throw "Neyvia window recording failed. Confirm that the desktop app is open and its title is '$WindowTitle'."
}

$framePattern = Join-Path $framesDirectory "frame-%03d.png"
& $ffmpeg -hide_banner -loglevel warning -y -i $videoPath -vf "fps=1/$FrameEverySeconds" $framePattern
if ($LASTEXITCODE -ne 0) {
    throw "The MP4 was recorded, but timed proof-frame extraction failed."
}

$durationText = (& $ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 $videoPath).Trim()
$frameFiles = @(Get-ChildItem -LiteralPath $framesDirectory -Filter "*.png" -File | Sort-Object Name)
$hash = (Get-FileHash -LiteralPath $videoPath -Algorithm SHA256).Hash.ToLowerInvariant()
$receipt = [ordered]@{
    schema = "neyvia.ui_recording_receipt.v1"
    recordedAt = (Get-Date).ToUniversalTime().ToString("o")
    captureScope = "application-window"
    windowTitle = $WindowTitle
    videoPath = $videoPath
    videoSha256 = $hash
    durationSeconds = [math]::Round([double]$durationText, 3)
    frameEverySeconds = $FrameEverySeconds
    frameCount = $frameFiles.Count
    framesDirectory = $framesDirectory
    audioCaptured = $false
    privacy = "Only the named Neyvia window was captured; desktop audio and other windows were excluded."
}
$receipt | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $receiptPath -Encoding utf8

Write-Host "Recording: $videoPath"
Write-Host "Frames: $framesDirectory"
Write-Host "Receipt: $receiptPath"
