# Generate Chinese narration with Windows SAPI.
# This script must stay pure ASCII: powershell.exe reads .ps1 as ANSI, so any
# non-ASCII literal (including Chinese paths) would be mangled. Paths are derived
# at runtime via $PSScriptRoot; Chinese text lives in lines.txt (UTF-8).

Add-Type -AssemblyName System.Speech

$base = $PSScriptRoot
$outDir = Join-Path (Split-Path $base -Parent) "intro"
$linesFile = Join-Path $base "lines.txt"

if (-not (Test-Path $outDir)) { New-Item -ItemType Directory -Path $outDir | Out-Null }

$lines = Get-Content -LiteralPath $linesFile -Encoding UTF8

$i = 1
foreach ($line in $lines) {
    if ([string]::IsNullOrWhiteSpace($line)) { continue }

    $path = Join-Path $outDir ("voice-" + $i + ".wav")

    $s = New-Object System.Speech.Synthesis.SpeechSynthesizer
    $s.SelectVoice("Microsoft Huihui Desktop")
    $s.Rate = 0
    $s.Volume = 100
    $s.SetOutputToWaveFile($path)
    $s.Speak($line)
    $s.Dispose()

    $kb = [math]::Round((Get-Item $path).Length / 1024, 1)
    Write-Host ("voice-" + $i + ".wav  " + $kb + " KB")

    $i++
}

Write-Host "done."
