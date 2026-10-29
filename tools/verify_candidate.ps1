<#
.SYNOPSIS
  Local acceptance of a candidate release (S67). Verifies a candidate commit in its OWN checkout and environment, against your installed app's
  configuration and a COPY of your record. Changes nothing of yours: the running app, its .venv, its store, your working tree.

.DESCRIPTION
  1. clones the candidate into <AppFolder>\verify\candidate (a separate clone; your workshop's dirty files are never touched)
  2. builds <AppFolder>\verify\venv from the candidate's requirements.lock (a separate environment; the app's .venv is never touched)
  3. runs `pflab verify` from there: prerequisites, sandbox containment probe, read-only Kite and Gmail reads, the candidate's migrations on a
     copy, an upgrade -> write -> rollback rehearsal on copies, a force-kill and restart drill, freshness, and a before/after proof that the
     live ledger file is unchanged
  4. writes a sanitized report to <AppFolder>\verify\report.txt (and report.json)
  It is resumable: do the steps it lists under "Next, in order" (Kite login, Gmail connect, Docker start, close the dashboard) and run it again.
  Steps no program can do (a real laptop sleep) are listed, and `-WakeCheck` verifies them afterwards.

.PARAMETER Ref        the candidate on GitHub: a branch, tag or commit (default: the S67 candidate branch)
.PARAMETER Repo       your workshop checkout, only used to find the GitHub address (default D:\portfolio_lab)
.PARAMETER AppFolder  the installed app's folder (default D:\PortfolioLabApp)
.PARAMETER WakeCheck  after the laptop has really slept with the app open: did the app see and recover from it?
.PARAMETER LiveModel  also one small model call through the app's privacy gate and budget (costs well under a rupee)
.PARAMETER Offline    do not contact Kite or Gmail
#>
param(
  [string]$Ref = "claude/wonderful-bardeen-z07h1e",
  [string]$Repo = "D:\portfolio_lab",
  [string]$AppFolder = "D:\PortfolioLabApp",
  [switch]$WakeCheck,
  [switch]$LiveModel,
  [switch]$Offline
)
$ErrorActionPreference = "Stop"
function Step($t) { Write-Host "`n== $t" -ForegroundColor Cyan }

Step "prerequisites"
if (-not (Get-Command git -ErrorAction SilentlyContinue)) { throw "git is not on PATH" }
$py = (Get-Command python -ErrorAction SilentlyContinue)
if (-not $py) { throw "python is not on PATH (3.13 is what the app uses)" }
if (-not (Test-Path $AppFolder)) { throw "no app folder at $AppFolder (use -AppFolder)" }
$verify = Join-Path $AppFolder "verify"
New-Item -ItemType Directory -Force -Path $verify | Out-Null

Step "the candidate, in its own clone ($Ref)"
$origin = (& git -C $Repo remote get-url origin).Trim()
if (-not $origin) { throw "cannot read the GitHub address from $Repo (use -Repo)" }
$cand = Join-Path $verify "candidate"
if (-not (Test-Path (Join-Path $cand ".git"))) { & git clone --quiet --no-checkout $origin $cand; if ($LASTEXITCODE) { throw "git clone failed" } }
& git -C $cand fetch --quiet --tags --force origin; if ($LASTEXITCODE) { throw "git fetch failed" }
& git -C $cand reset --quiet --hard 2>$null
$target = (& git -C $cand rev-parse --verify --quiet "origin/$Ref")
if (-not $target) { $target = (& git -C $cand rev-parse --verify --quiet "$Ref^{commit}") }
if (-not $target) { throw "cannot find $Ref on GitHub" }
& git -C $cand checkout --quiet --detach $target; if ($LASTEXITCODE) { throw "git checkout failed" }
Write-Host ("candidate commit " + (& git -C $cand rev-parse --short=12 HEAD).Trim())

Step "the candidate's own environment (the app's .venv is not touched)"
$venv = Join-Path $verify "venv"
if (-not (Test-Path (Join-Path $venv "Scripts\python.exe"))) { & python -m venv $venv; if ($LASTEXITCODE) { throw "venv failed" } }
$vpy = Join-Path $venv "Scripts\python.exe"
$lock = Join-Path $cand "requirements.lock"
$hash = (Get-FileHash $lock -Algorithm SHA256).Hash
$mark = Join-Path $venv ".lockhash"
if ((-not (Test-Path $mark)) -or ((Get-Content $mark -Raw).Trim() -ne $hash)) {
  & $vpy -m pip install --quiet --upgrade pip
  & $vpy -m pip install --quiet -r $lock; if ($LASTEXITCODE) { throw "installing requirements.lock failed" }
  & $vpy -m pip install --quiet --no-deps -e $cand; if ($LASTEXITCODE) { throw "installing the candidate failed" }
  Set-Content -Path $mark -Value $hash -Encoding ASCII
}

Step "pflab verify"
$args2 = @("-m", "pflab.cli", "verify", "--app", $AppFolder, "--report", (Join-Path $verify "report.txt"))
if ($WakeCheck) { $args2 += "--wake-check" }
if ($LiveModel) { $args2 += "--live-model" }
if ($Offline)   { $args2 += "--offline" }
if ($LiveModel) { $env:PFLAB_CHANNEL = "stable"; $env:PFLAB_PAID = "1" }
Push-Location $cand
try { & $vpy @args2; $rc = $LASTEXITCODE } finally { Pop-Location }
Write-Host "`nreport: $(Join-Path $verify 'report.txt')"
exit $rc
