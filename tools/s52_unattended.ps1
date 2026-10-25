# S52 TimesFM done properly, end to end and unattended (docs/research/timesfm2_protocol.md, amendments 1-2).
#
#   cd D:\portfolio_lab
#   powershell -ExecutionPolicy Bypass -File tools\s52_unattended.ps1            # everything, offline, ~5-7 h
#   powershell -ExecutionPolicy Bypass -File tools\s52_unattended.ps1 -DryRun    # print the plan only
#
# Offline: the TimesFM weights are in the Hugging Face cache (HF_HUB_OFFLINE=1). Needs the GPU to itself: it refuses
# to start while the S47 run (llm harness) is still going. Every step resumes after an interruption (forecasts are
# written per file, fine-tuning checkpoints every 250 steps): if it stops, run the same command again.
# Steps: prepare inputs -> memory probes -> fine-tune forward check -> zero-shot forecasts (Q1, Q3, Q5, Q6)
#   -> development choice -> fine-tuning (Q1 by market fold, Q6 by company fold) -> fine-tuned forecasts -> evaluation.
# Keeps the laptop awake with the screen on; GPU telemetry in PFLAB_PM_DIR\reports\s52_gpu_<date>.csv.
# Log: PFLAB_PM_DIR\reports\s52_<date>.log; ends with FINISHED and the RESULT lines (send them to Claude).
param([switch]$DryRun)

$ErrorActionPreference = "Continue"
Set-Location (Split-Path $PSScriptRoot -Parent)
$env:PYTHONIOENCODING = "utf-8"
$env:HF_HUB_OFFLINE = "1"
$py = (Resolve-Path ".venv\Scripts\python.exe").Path
$pyt = (Resolve-Path ".venv-train\Scripts\python.exe").Path
$pm = if ($env:PFLAB_PM_DIR) { $env:PFLAB_PM_DIR } else { "D:\portfolio_lab\pm" }
$day = Get-Date -Format "yyyy-MM-dd"
$log = "$pm\reports\s52_$day.log"
$tmp = "$pm\reports\_s52step"
New-Item -ItemType Directory -Force "$pm\reports" | Out-Null

function Log($msg) {
    $line = "{0}  {1}" -f (Get-Date -Format "HH:mm:ss"), $msg
    Write-Host $line
    Add-Content -Path $log -Value $line -Encoding utf8
}

function Step($name, $exe, [string]$args_, [int]$minutes, [string]$mustSay, [int]$tries = 1) {
    foreach ($try in 1..$tries) {
        if ($DryRun) { Log "would run: $name (limit $minutes min)"; return $true }
        Log "START $name$(if ($tries -gt 1) { ", attempt $try of $tries" })"
        $t0 = Get-Date
        Remove-Item "$tmp.out", "$tmp.err" -ErrorAction SilentlyContinue
        $p = Start-Process -FilePath $exe -ArgumentList $args_ -NoNewWindow -PassThru `
            -RedirectStandardOutput "$tmp.out" -RedirectStandardError "$tmp.err"
        $null = $p.Handle
        $done = $p.WaitForExit($minutes * 60 * 1000)
        if (-not $done) { & taskkill /T /F /PID $p.Id *> $null; Start-Sleep -Seconds 2 }
        $out = (Get-Content "$tmp.out" -Raw -Encoding UTF8 -ErrorAction SilentlyContinue)
        $err = (Get-Content "$tmp.err" -Raw -Encoding UTF8 -ErrorAction SilentlyContinue)
        if ($null -eq $out) { $out = "" }
        Add-Content -Path $log -Value $out -Encoding utf8
        $ok = $done -and $p.ExitCode -eq 0 -and $out -match [regex]::Escape($mustSay)
        if (-not $ok -and $err) { Add-Content -Path $log -Value ($err.Substring([math]::Max(0, $err.Length - 3000))) -Encoding utf8 }
        Log ("END ${name}: " + $(if (-not $done) { "TIMEOUT" } elseif ($ok) { "ok ($([math]::Round(((Get-Date) - $t0).TotalMinutes, 1)) min)" } else { "FAILED (see above)" }))
        if ($ok) { return $true }
        if (-not (GpuPresent)) {                       # 2026-10-21: the GPU dropped off the bus; retrying cannot help
            Log "GPU LOST (nvidia-smi cannot see it). Save your work, use Start > Power > Restart (not Shut down), then run this again: it resumes."
            $script:gpuLost = $true
            return $false
        }
        if ($try -lt $tries) { Log "resuming in 1 minute"; Start-Sleep -Seconds 60 }
    }
    return $false
}

function GpuPresent {
    $q = & nvidia-smi --query-gpu=name --format=csv,noheader 2>&1 | Out-String
    return ($LASTEXITCODE -eq 0) -and ($q -notmatch "lost|No devices")
}
$gpuLost = $false

$busy = Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match "llm harness|timesfm2_forecast|timesfm2_finetune" }
if ($busy -and -not $DryRun) {
    Write-Host "Another GPU job is running (S47 harness or an earlier S52 run): wait for it to finish, then run this again."
    exit 2
}

Add-Type -Namespace PfLabS52 -Name Power -MemberDefinition '[DllImport("kernel32.dll")] public static extern uint SetThreadExecutionState(uint esFlags);'
[PfLabS52.Power]::SetThreadExecutionState([uint32]"0x80000003") | Out-Null      # awake, screen on (no Modern Standby)
$gpu = $null
try {
    Log "S52 TimesFM unattended run $day$(if ($DryRun) { ' (DRY RUN)' })"
    if (-not $DryRun) {
        # 2026-10-21: the GPU dropped off the bus three times at its top boost (14 GHz memory); capped clocks held.
        # The caps last until a reboot, so the run sets them itself when it can (Administrator PowerShell).
        $admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
            [Security.Principal.WindowsBuiltInRole]::Administrator)
        if ($admin) {
            $g = & nvidia-smi -lgc 210,2100 2>&1 | Out-String
            $m = & nvidia-smi -lmc 405,9001 2>&1 | Out-String
            Log ("GPU clocks capped (core 2100, memory 9001 MHz): " + (($g + " " + $m) -replace '\s+', ' ').Trim())
        } else {
            Log "NOTE: not an Administrator PowerShell, so the GPU clock caps were not set by this run. If you have rebooted since setting them, stop (Ctrl+C), open PowerShell as Administrator and start this again."
        }
        & ollama stop qwen3:8b-q8_0 *> $null                                   # free the GPU if the agents' model is loaded
        $gpu = Start-Process powershell -ArgumentList "-ExecutionPolicy Bypass -File tools\gpu_log.ps1 -Out $pm\reports\s52_gpu_$day.csv" -WindowStyle Hidden -PassThru
    }
    $ok = Step "prepare inputs" $py "tools\timesfm2_study.py prepare" 30 "PREPARE DONE"
    if ($ok) { $ok = Step "memory probe, forecasting (worst case)" $pyt "tools\timesfm2_forecast.py probe" 15 "probe 3.0" }
    if ($ok) { $ok = Step "memory probe, fine-tuning (worst case)" $pyt "tools\timesfm2_finetune.py probe" 15 "probe:" }
    $ft = $false
    if ($ok) { $ft = Step "fine-tune forward check (must equal the library)" $pyt "tools\timesfm2_finetune.py check" 15 "CHECK OK" }
    if ($ok -and -not $ft -and -not $DryRun) { Log "CHECK FAILED: F25 and C are dropped (amendment 2); the zero-shot candidates go on" }
    if ($ok) { $ok = Step "zero-shot forecasts Q1 Q3 Q5 Q6" $pyt "tools\timesfm2_forecast.py run --tasks q1,q3,q5,q6 --cands T25,T30,T30X,T30C" 480 "FORECASTS DONE" 3 }
    if ($ok -and $ft) {
        $ok = Step "development choice for fine-tuning" $py "tools\timesfm2_study.py dev-choice" 20 "dev choice:"
        if ($ok) { $ok = Step "fine-tuning Q1 (two market folds, two ranks)" $pyt "tools\timesfm2_finetune.py q1" 360 "FINETUNE DONE" 3 }
        if ($ok) { $ok = Step "fine-tuning Q6 (two company folds, two targets)" $pyt "tools\timesfm2_finetune.py q6" 240 "FINETUNE DONE" 3 }
        if ($ok) { $ok = Step "fine-tuned forecasts Q1 Q6" $pyt "tools\timesfm2_forecast.py run --tasks q1,q6 --cands F25" 120 "FORECASTS DONE" 3 }
    }
    if ($ok) {
        $ok = Step "evaluation (registered rules)" $py "tools\timesfm2_study.py evaluate" 60 "EVALUATE DONE"
        $res = Select-String -Path $log -CaseSensitive -Pattern "^(Q1 adopt|Q3 h=|Q3b|Q4:|Q5 adopt|Q6 adopt)" | ForEach-Object { $_.Line }
        foreach ($r in $res) { Log "RESULT: $r" }
    }
    if (-not $ok -and -not $DryRun) {
        if ($gpuLost) { Log "STOPPED: the GPU was lost. Restart Windows (Restart, not Shut down), then run the same command (it resumes)" }
        else { Log "STOPPED before the end: run the same command again (it resumes)" }
    }
    elseif (-not $DryRun) { [console]::Beep(880, 300); [console]::Beep(660, 300) }
    Log "FINISHED"
}
finally {
    if ($gpu) { & taskkill /T /F /PID $gpu.Id *> $null }
    Remove-Item "$tmp.out", "$tmp.err" -ErrorAction SilentlyContinue
    [PfLabS52.Power]::SetThreadExecutionState([uint32]"0x80000000") | Out-Null
}
