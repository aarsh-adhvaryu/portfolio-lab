<#
.SYNOPSIS
  Registers the ONE Windows Task Scheduler entry the Portfolio Manager needs. NOT RUN BY CLAUDE.
  The investor reviews and runs it (PLAN S9: "approve the Task Scheduler entries").

.DESCRIPTION
  The entry runs `pflab service tick` every 15 minutes, at logon, and at wake from sleep. Every job
  decides for itself whether it is due, so more frequent ticks cost nothing and a laptop that slept
  for days catches up on the first tick after wake. The ledger jobs need no admin rights.

  Preview first:   .\tools\register_tasks.ps1 -WhatIf
  Register:        .\tools\register_tasks.ps1
  Remove:          Unregister-ScheduledTask -TaskName "PFLab Tick" -Confirm:$false

  UNTESTED on this machine as of 2026-10-06 (registration is the investor's step). After registering, run
  `pflab service status` and look for "job:..." lines turning OK within a quarter of an hour.
#>
[CmdletBinding(SupportsShouldProcess = $true)]
param(
  [string]$RepoRoot = (Split-Path -Parent $PSScriptRoot),
  [string]$TaskName = "PFLab Tick"
)

# S65: only an installed app registers its tick. The workshop (a checkout with no release.toml) never does: two ticks on one
# phone would answer twice (src\pflab\guard.py).
if (-not (Test-Path (Join-Path $RepoRoot "release.toml"))) {
  throw "no release.toml in $RepoRoot: this is the workshop. Scheduled tasks are registered only for the installed app (tools\install_app.ps1)."
}

# pythonw: no console window flashing up every 15 minutes (S58b); the tick writes to PFLAB_PM_DIR\reports\tick.log.
# While the dashboard is open the tick stands aside (the dashboard runs the jobs); its Settings decide the preset and
# whether held messages are sent, for the tick too.
$py = Join-Path $RepoRoot ".venv\Scripts\pythonw.exe"
if (-not (Test-Path $py)) { throw "no .venv pythonw at $py" }

$action = New-ScheduledTaskAction -Execute $py -Argument "-m pflab.cli service tick" -WorkingDirectory $RepoRoot

$every15 = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) `
            -RepetitionInterval (New-TimeSpan -Minutes 15)
$atLogon = New-ScheduledTaskTrigger -AtLogOn

# Wake from sleep: the Power-Troubleshooter event 1 is written on resume.
$cimClass = Get-CimClass -ClassName MSFT_TaskEventTrigger -Namespace Root/Microsoft/Windows/TaskScheduler
$onWake = New-CimInstance -CimClass $cimClass -ClientOnly
$onWake.Enabled = $true
$onWake.Subscription = '<QueryList><Query Id="0" Path="System"><Select Path="System">*[System[Provider[@Name=''Microsoft-Windows-Power-Troubleshooter''] and EventID=1]]</Select></Query></QueryList>'

$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew `
              -ExecutionTimeLimit (New-TimeSpan -Hours 3) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries

if ($PSCmdlet.ShouldProcess($TaskName, "Register scheduled task (runs pflab service tick)")) {
  Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger @($every15, $atLogon, $onWake) `
    -Settings $settings -Description "Portfolio Manager: run due jobs (collect, prices, NAV, filings, outbox, backup)" -Force | Out-Null
  Write-Host "Registered '$TaskName'. Check: pflab service status"
}
