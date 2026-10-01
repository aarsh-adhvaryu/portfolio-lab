# overnight_queue.ps1 -- run the pending jobs, at most four at once (CLAUDE.md,
# "Running jobs"), each in its own hidden PowerShell, in RUNNING.md order.
#
#   .\tools\overnight_queue.ps1            start (skips jobs already marked done)
#   .\tools\overnight_queue.ps1 -Status    morning check: one line per job
#   .\tools\overnight_queue.ps1 -Only 26,30  run just these jobs
#
# Each job logs to logs\overnight\<job>.log and ends with <job>.done or
# <job>.failed (the reason is inside). A failure never stops the others.
# A job is done only if it exited 0 AND its log carries its success line
# (a sweep can exit 0 and still have failed: CLAUDE.md).
param([switch]$Status, [int[]]$Only, [int]$MaxParallel = 4)

$ErrorActionPreference = 'Stop'
$Repo = 'D:\portfolio_lab'
$LogDir = Join-Path $Repo 'logs\overnight'
New-Item -ItemType Directory -Force $LogDir | Out-Null
$Py = "$Repo\.venv\Scripts\python.exe"
$Exp = "$Repo\experiments"
$StackRef = "$Exp\E1d\regression\validation-a6256fbb0ba71a8f\rows\base"

function Locked($id, $exp, $period, $cfg) {
  @{ id = $id; net = $false; cwd = $Repo; ok = 'SWEEP DIR:'
     cmd = ".\tools\run_locked.ps1 -Experiment $exp -Period $period -Config $cfg" }
}
function Identity($id, $wt, $tag) {
  @{ id = $id; net = $false; cwd = "D:\pl_runs\$wt"; ok = 'IDENTICAL'
     must = "pflab imported from D:\pl_runs\$wt"
     cmd = "`$env:PYTHONPATH='D:\pl_runs\$wt\src'; & '$Py' -u '$Repo\tools\e1_identity.py' validation --config configs/e1d.toml --ref '$StackRef'" }
}

# Order is RUNNING.md's. net = needs the internet.
$Jobs = @(
  @{ id = 23; net = $true; cwd = $Repo; ok = 'DONE:'
     cmd = "& '$Py' -u tools\probe_bse_results.py pull" },
  (Locked 26 'E5-A-A1'  'validation' 'configs\e5a_a1.toml'),
  (Locked 27 'E5-A-A3'  'validation' 'configs\e5a_a3.toml'),
  (Locked 28 'E5-A-A2'  'validation' 'configs\e5a_a2.toml'),
  (Locked 29 'E5-A-ALL' 'validation' 'configs\e5a_all.toml'),
  (Identity 30 'E5-A-A1' '6a29dde'),
  (Identity 31 'E5-A-A2' '31a4b7c'),
  (Locked 32 'E5-A-A5'  'e5a_development' 'configs\e5a_a5.toml')
)
if ($Only) { $Jobs = $Jobs | Where-Object { $Only -contains $_.id } }

function Mark($j) {
  $b = Join-Path $LogDir "job$($j.id)"
  if (Test-Path "$b.done") { 'done' } elseif (Test-Path "$b.failed") { 'failed' }
  elseif (Test-Path "$b.running") { 'running' } else { 'pending' }
}

if ($Status) {
  $free = [math]::Round((Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory / 1MB, 1)
  "free RAM $free GB; queue runner alive: " + [bool](Get-Content "$LogDir\queue.pid" -ErrorAction SilentlyContinue | ForEach-Object { Get-Process -Id $_ -ErrorAction SilentlyContinue })
  foreach ($j in $Jobs) {
    $b = Join-Path $LogDir "job$($j.id)"
    $m = Mark $j
    $why = if ($m -eq 'failed') { (Get-Content "$b.failed" -Raw).Trim() } elseif ($m -eq 'done') { (Get-Content "$b.done" -Raw).Trim() } else { '' }
    $last = if (Test-Path "$b.log") { (Get-Content "$b.log" -Tail 1) } else { '' }
    "{0,-4} {1,-8} {2}  {3}" -f $j.id, $m, $why, $last
  }
  return
}

$PID | Set-Content "$LogDir\queue.pid"
"queue started $(Get-Date -Format s); jobs: $(($Jobs | ForEach-Object { $_.id }) -join ', ')" | Tee-Object -Append "$LogDir\queue.log"
$pending = [System.Collections.ArrayList]@($Jobs | Where-Object { (Mark $_) -ne 'done' })
$running = @{}

function Finish($j, $p) {
  $b = Join-Path $LogDir "job$($j.id)"
  $rc = $p.ExitCode
  $log = if (Test-Path "$b.log") { Get-Content "$b.log" -Raw } else { '' }
  $why = $null
  if ($rc -ne 0) { $why = "exit $rc" }
  elseif ($log -notmatch [regex]::Escape($j.ok)) { $why = "exit 0 but no '$($j.ok)' in the log" }
  elseif ($j.must -and $log -notmatch [regex]::Escape($j.must)) { $why = "pflab not imported from the worktree" }
  elseif ($log -match 'Traceback') { $why = 'Traceback in the log' }
  Remove-Item "$b.running" -ErrorAction SilentlyContinue
  $t = Get-Date -Format s
  if ($why) { "$t $why" | Set-Content "$b.failed" } else { "$t ok" | Set-Content "$b.done" }
  "$t job$($j.id) " + $(if ($why) { "FAILED: $why" } else { 'done' }) | Tee-Object -Append "$LogDir\queue.log"
}

while ($pending.Count -or $running.Count) {
  foreach ($id in @($running.Keys)) {
    $r = $running[$id]
    if ($r.p.HasExited) { Finish $r.j $r.p; $running.Remove($id) }
  }
  while ($pending.Count -and $running.Count -lt $MaxParallel) {
    $j = $pending[0]; $pending.RemoveAt(0)
    $b = Join-Path $LogDir "job$($j.id)"
    Remove-Item "$b.failed", "$b.done" -ErrorAction SilentlyContinue
    (Get-Date -Format s) | Set-Content "$b.running"
    $cmd = "`$ErrorActionPreference='Continue'; `$env:PFLAB_EXPERIMENTS_DIR='$Exp'; `$env:PFLAB_DATA_DIR='$Repo\data'; " +
           "Set-Location '$($j.cwd)'; $($j.cmd) *>&1 | ForEach-Object { `"`$_`" } | Out-File -Encoding utf8 '$b.log'; exit `$LASTEXITCODE"
    $p = Start-Process powershell.exe -WindowStyle Hidden -PassThru -ArgumentList @(
      '-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command', $cmd)
    $null = $p.Handle            # keeps ExitCode readable after exit
    $running[$j.id] = @{ j = $j; p = $p }
    "$(Get-Date -Format s) job$($j.id) started (pid $($p.Id))" | Tee-Object -Append "$LogDir\queue.log"
  }
  Start-Sleep -Seconds 30
}
"queue finished $(Get-Date -Format s)" | Tee-Object -Append "$LogDir\queue.log"
