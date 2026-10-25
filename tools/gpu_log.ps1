# GPU telemetry for long GPU jobs: one nvidia-smi reading every few seconds, appended at once (nvidia-smi's own -l/-f
# keeps its output in memory, so a power cut would lose it). Stopped by killing the process.
#   powershell -ExecutionPolicy Bypass -File tools\gpu_log.ps1 -Out <file.csv> [-Seconds 5]
param([Parameter(Mandatory = $true)][string]$Out, [int]$Seconds = 5)
$fields = "timestamp,temperature.gpu,power.draw,clocks.gr,clocks.mem,utilization.gpu,memory.used,clocks_event_reasons.active"
if (-not (Test-Path $Out)) { Add-Content -Path $Out -Value $fields -Encoding utf8 }
while ($true) {
    $row = & nvidia-smi "--query-gpu=$fields" "--format=csv,noheader,nounits" 2>&1
    Add-Content -Path $Out -Value $row -Encoding utf8
    Start-Sleep -Seconds $Seconds
}
