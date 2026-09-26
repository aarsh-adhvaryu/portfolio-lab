<#
.SYNOPSIS
  Run a LOCKED experiment's sweep from its frozen code.

.DESCRIPTION
  GATE.md rule 4 (2026-09-26): an experiment's development and validation
  sweeps run on the same frozen code, its lock commit. With several
  experiments in flight the working tree changes under a run that takes an
  hour, and two halves of one verdict computed on different code are not one
  verdict.

  This script refuses to run unless:
    * the tag lock/<ID> exists, and
    * the charter's locked-span hash still matches what was recorded at the
      lock (tools/check_lock.py), and
    * the run worktree D:\pl_runs\<ID> exists, and
    * the pflab that actually gets imported lives INSIDE that worktree.

  The last check is the one that matters most and the easiest to get wrong.
  The repo is installed editable, so `import pflab` normally resolves to
  D:\portfolio_lab\src\pflab -- the LIVE tree. Setting PYTHONPATH is not
  enough on its own to be sure, so the script imports pflab, prints its
  __file__, and aborts if that path is not under the worktree. A run that
  silently used live code would produce numbers indistinguishable from a
  correct run.

.EXAMPLE
  .\tools\run_locked.ps1 -Experiment E1d -Period development
#>
[CmdletBinding()]
param(
  [Parameter(Mandatory = $true)][string]$Experiment,
  [Parameter(Mandatory = $true)][string]$Period,
  [string]$Config,
  [switch]$EventStudy,
  [switch]$WhatIf
)

$ErrorActionPreference = "Stop"
$Repo     = "D:\portfolio_lab"
$RunRoot  = "D:\pl_runs\$Experiment"
$Py       = "$Repo\.venv\Scripts\python.exe"
$DataDir  = "D:\portfolio_lab\data"
$ExpDir   = "D:\portfolio_lab\experiments"

function Fail($msg) { Write-Host "REFUSED: $msg" -ForegroundColor Red; exit 2 }
function Say($msg)  { Write-Host $msg -ForegroundColor Cyan }

Set-Location $Repo

# --- 1. the lock -------------------------------------------------------
Say "== checking the lock =="
& $Py "$Repo\tools\check_lock.py" $Experiment
if ($LASTEXITCODE -ne 0) { Fail "$Experiment is not soundly locked (see above)" }

# --- 2. the run worktree ----------------------------------------------
if (-not (Test-Path $RunRoot)) {
  Fail "run worktree $RunRoot does not exist. Create it with:`n" +
       "  git -C $Repo worktree add --detach $RunRoot lock/$Experiment"
}
$wtSrc = Join-Path $RunRoot "src"
if (-not (Test-Path $wtSrc)) { Fail "$wtSrc not found -- is $RunRoot a pflab worktree?" }

# --- 3. the environment the run will see ------------------------------
$env:PYTHONPATH             = $wtSrc
$env:PFLAB_DATA_DIR         = $DataDir
$env:PFLAB_EXPERIMENTS_DIR  = $ExpDir

# --- 4. prove the FROZEN pflab is the one that imports ----------------
Say "== checking which pflab imports =="
$probe = @"
import pflab, os, sys
p = os.path.abspath(pflab.__file__)
print(p)
want = os.path.abspath(r'$wtSrc')
sys.exit(0 if p.lower().startswith(want.lower()) else 3)
"@
$imported = & $Py -c $probe
Write-Host "  pflab.__file__ = $imported"
if ($LASTEXITCODE -ne 0) {
  Fail ("the pflab that imports is NOT inside $wtSrc.`n" +
        "  imported: $imported`n" +
        "  The editable install shadows PYTHONPATH. Run this script from a " +
        "shell where the venv's .pth does not point at $Repo\src, or use a " +
        "venv created inside the worktree.")
}

$tagSha = (git -C $Repo rev-list -n 1 "lock/$Experiment").Trim()
$cfg = if ($Config) { $Config } else { "configs/$($Experiment.ToLower().Replace('-','')).toml" }
if (-not (Test-Path (Join-Path $RunRoot $cfg))) {
  Fail "config $cfg not found inside $RunRoot"
}

# --- 5. expected duration, before anything starts ---------------------
$mins = switch -Regex ($Experiment) {
  "E1d"  { 35 }; "E2-A" { 30 }; default { 30 }
}
Say ""
Say "== about to run =="
Write-Host "  experiment : $Experiment   period: $Period"
Write-Host "  tag        : lock/$Experiment -> $($tagSha.Substring(0,12))"
Write-Host "  code from  : $wtSrc"
Write-Host "  config     : $cfg"
Write-Host "  data       : $DataDir"
Write-Host "  results    : $ExpDir"
Write-Host "  EXPECTED DURATION: about $mins minutes. Check tools\status.ps1"
Write-Host "  before starting another -- see CLAUDE.md for how many may run at once."
if ($WhatIf) { Say "`n-WhatIf: stopping before the run."; exit 0 }

# --- 6. run, tee'd to a log -------------------------------------------
$logDir = Join-Path $ExpDir "$Experiment\logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$log = Join-Path $logDir "$Period-$stamp.log"
Say "`n== running; log: $log =="

$runner = @"
import json, sys
from pflab.backtest import runner
out = runner.main(r'$cfg', '$Period', None, sweep=True,
                  extra_manifest={'lock_tag': 'lock/$Experiment',
                                  'lock_commit': '$tagSha',
                                  'code_path': r'$wtSrc'})
print('SWEEP DIR: ' + str(out))
"@

Push-Location $RunRoot
try {
  & $Py -u -c $runner 2>&1 | Tee-Object -FilePath $log
  $rc = $LASTEXITCODE
} finally { Pop-Location }

if ($rc -ne 0) { Write-Host "`nsweep exited $rc -- read $log" -ForegroundColor Red; exit $rc }

if ($EventStudy) {
  Say "`n== event study =="
  Push-Location $RunRoot
  try { & $Py -u "$RunRoot\tools\run_event_study.py" $Period 2>&1 | Tee-Object -FilePath $log -Append }
  finally { Pop-Location }
}

Say "`nDONE. Results under $ExpDir\$Experiment. Log: $log"
Write-Host "Read the numbers off disk (criteria.json, summary.md) rather than"
Write-Host "trusting this message -- a sweep can exit 0 and still have failed."
