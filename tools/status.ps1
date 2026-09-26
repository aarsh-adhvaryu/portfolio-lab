<#
.SYNOPSIS
  What is running right now. Read-only.

.DESCRIPTION
  Every sweep (experiment, period, rows done of total read from its log,
  elapsed, estimated remaining, RAM), every backfill, and free RAM.

  This reads the process table and the logs on disk. It never trusts a
  completion notice: on this machine a background task has reported exit 0
  over a Python traceback, a 0-byte log has meant "buffered" rather than
  "not running", and a `ps | grep` could not see Windows command lines and
  declared a live sweep dead. The process table and the artifacts are the
  reliable signals.
#>
[CmdletBinding()] param()

$ExpDir = if ($env:PFLAB_EXPERIMENTS_DIR) { $env:PFLAB_EXPERIMENTS_DIR } else { "D:\portfolio_lab\experiments" }

$os   = Get-CimInstance Win32_OperatingSystem
$freeGB  = [math]::Round($os.FreePhysicalMemory / 1MB, 1)
$totalGB = [math]::Round($os.TotalVisibleMemorySize / 1MB, 1)

$procs = Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
  Where-Object { $_.CommandLine -match "runner\.main|backfill_|run_event_study|red_flag_events" }

Write-Host ""
Write-Host "RAM: $freeGB GB free of $totalGB GB" -ForegroundColor Cyan
Write-Host ""

if (-not $procs) {
  Write-Host "No sweeps, event studies or backfills running." -ForegroundColor Green
} else {
  Write-Host ("{0,-7} {1,-9} {2,-16} {3,-9} {4,-9} {5,-9} {6}" -f `
              "PID", "KIND", "WHAT", "RAM(GB)", "ELAPSED", "PROGRESS", "EST LEFT")
  foreach ($p in $procs) {
    $ps = Get-Process -Id $p.ProcessId -ErrorAction SilentlyContinue
    if (-not $ps) { continue }
    # the venv python is a launcher shim: 1 thread, no CPU. Count locks and
    # real workers, not process rows (2026-09-24).
    if ($ps.Threads.Count -le 2 -and $ps.CPU -lt 2) { continue }

    $cl = $p.CommandLine
    $kind = if ($cl -match "backfill_")        { "backfill" }
            elseif ($cl -match "run_event_study") { "study" }
            elseif ($cl -match "red_flag_events") { "flagtbl" }
            else { "sweep" }

    $what = "-"
    if ($cl -match "--shard\s+(\d+)\s+--of\s+(\d+)") { $what = "shard $($Matches[1])/$($Matches[2])" }
    elseif ($cl -match "'([^']*development[^']*)'|'([^']*validation[^']*)'") {
      $what = ($Matches[1], $Matches[2] | Where-Object { $_ })[0]
    }

    $ramGB   = [math]::Round($ps.WorkingSet64 / 1GB, 2)
    $elapsed = (Get-Date) - $ps.StartTime
    $el      = "{0:hh\:mm\:ss}" -f $elapsed

    # rows done, from the newest log this experiment has
    $progress = "-"; $left = "-"
    $logs = Get-ChildItem "$ExpDir\*\logs\*.log" -ErrorAction SilentlyContinue |
            Sort-Object LastWriteTime -Descending
    foreach ($lg in $logs) {
      if (((Get-Date) - $lg.LastWriteTime).TotalMinutes -gt 120) { continue }
      $txt = Get-Content $lg.FullName -Tail 40 -ErrorAction SilentlyContinue
      $m = $txt | Select-String -Pattern "\[(\d+)/(\d+)\]" | Select-Object -Last 1
      if ($m) {
        $done = [int]$m.Matches[0].Groups[1].Value
        $tot  = [int]$m.Matches[0].Groups[2].Value
        $progress = "$done/$tot"
        if ($done -gt 0) {
          $per = $elapsed.TotalMinutes / $done
          $left = "{0:N0} min" -f ($per * ($tot - $done))
        }
        break
      }
    }
    if ($kind -eq "backfill") {
      $lockN = (Get-ChildItem "D:\portfolio_lab\data\bse_shareholding\_lock.*" -ErrorAction SilentlyContinue).Count
      $progress = "$lockN locks"
    }
    Write-Host ("{0,-7} {1,-9} {2,-16} {3,-9} {4,-9} {5,-9} {6}" -f `
                $p.ProcessId, $kind, $what, $ramGB, $el, $progress, $left)
  }
}

Write-Host ""
Write-Host "Queued / running / done jobs: docs\RUNNING.md"
Write-Host "How many sweeps may run at once: CLAUDE.md, 'Running jobs'"
