<#
.SYNOPSIS
  The one-time data copy from the workshop into the installed app (S65, docs/PLAN.md sections 3 and 7).

.DESCRIPTION
  Copies the workshop's NON-PERSONAL data (market data, news, filings, indices, F&O, US prices, the adjusted price panel) into the
  app's own data folder, leaving out what the app does not run on or what belongs to the old record (-Skip, -SkipFiles). By default the
  STORE is not copied: the app starts a fresh record (a complete reset, like an app); the learner's test counter is carried by code.
  -WithStore also copies the whole store folder pm\ (ledger, counter, suggestions, journal, answers). It REFUSES when the app already
  has a store or a data folder with files (the workshop's copy is never copied over the app's) and, with -WithStore, while the
  workshop's store is held by a running dashboard, bot or job. The workshop is left as it is.

  Preview:  powershell -ExecutionPolicy Bypass -File tools\seed_app.ps1 -DryRun
  Run:      powershell -ExecutionPolicy Bypass -File tools\seed_app.ps1 [-Folder D:\PortfolioLabApp]
  Duration: about 3 to 10 minutes for about 5 GB. Done when it prints "SEEDED" with the sizes.
#>
[CmdletBinding()]
param(
  [string]$Folder = "D:\PortfolioLabApp",
  [string]$WorkshopData = "",
  [string]$WorkshopPm = "",
  # not personal but not needed to run: evaluation and model files, the workshop's backups, llama.cpp, raw download caches, dev samples
  # and scratch; and what belongs to the old store or to his names: the learner's claim files, the graph's text, the collector's alias list
  [string[]]$Skip = @("llm_eval", "models", "backups", "tools", "raw", "a1_readers", "e5a", "flag_audit", "_probe", "_regression", "_shp",
                      "_bse", "_daily", "learner", "kg"),
  [string[]]$SkipFiles = @("comove.parquet", "gkg_aliases.json"),
  [switch]$WithStore,
  [switch]$DryRun
)
$ErrorActionPreference = "Stop"
$workshop = Split-Path -Parent $PSScriptRoot
$appRepo = Join-Path $Folder "app"
if (-not $WorkshopData) { $WorkshopData = if ($env:PFLAB_DATA_DIR) { $env:PFLAB_DATA_DIR } else { Join-Path $workshop "data" } }
if (-not $WorkshopPm) { $WorkshopPm = if ($env:PFLAB_PM_DIR) { $env:PFLAB_PM_DIR } else { Join-Path $workshop "pm" } }
$appData = Join-Path $Folder "data"
$appPm = Join-Path $Folder "pm"
function Fail([string]$m) { Write-Host "STOP: $m" -ForegroundColor Red; exit 1 }
function GB([long]$b) { [math]::Round($b / 1GB, 2) }
function SizeOf([string]$p, [string[]]$exclude = @()) {
  $sum = 0L
  Get-ChildItem $p -Force -ErrorAction SilentlyContinue | ForEach-Object {
    if ($_.PSIsContainer) { if ($exclude -notcontains $_.Name) { $sum += (Get-ChildItem $_.FullName -Recurse -File -Force -ErrorAction SilentlyContinue | Measure-Object Length -Sum).Sum } }
    else { $sum += $_.Length }
  }
  return $sum
}

if (-not (Test-Path (Join-Path $appRepo "release.toml"))) { Fail "$Folder is not an installed app (no app\release.toml): run tools\install_app.ps1 first" }
if (-not (Test-Path $WorkshopData)) { Fail "no workshop data at $WorkshopData" }
if ($WithStore -and -not (Test-Path $WorkshopPm)) { Fail "no workshop store folder at $WorkshopPm" }
if ((Test-Path (Join-Path $appPm "ledger.duckdb"))) { Fail "the app already has a store ($appPm\ledger.duckdb). It is his record: it is never overwritten from the workshop." }
if ((Test-Path $appData) -and (Get-ChildItem $appData -Force -ErrorAction SilentlyContinue | Select-Object -First 1)) { Fail "the app's data folder already has files: a seed is done once" }

# a store that a running process holds would be copied half-written
$py = Join-Path $workshop ".venv\Scripts\python.exe"
if ($WithStore) {
  & $py -W ignore -c "import sys; from pathlib import Path; from pflab.pm.reset import holds_store; sys.exit(1 if holds_store(Path(sys.argv[1])) else 0)" $WorkshopPm
  if ($LASTEXITCODE) { Fail "the workshop's store is held by a running process (the dashboard, the bot or a job): close it first" }
}

$dataBytes = SizeOf $WorkshopData $Skip
$pmBytes = if ($WithStore) { SizeOf $WorkshopPm } else { 0L }
$freeBytes = (Get-PSDrive ($Folder.Substring(0, 1))).Free
$storeNote = if ($WithStore) { "$(GB $pmBytes) GB, copied" } else { "not copied: a fresh record" }
Write-Host "workshop data: $(GB $dataBytes) GB (leaving out: $($Skip -join ', '); files: $($SkipFiles -join ', ')); store: $storeNote; free at the app: $(GB $freeBytes) GB"
if ($freeBytes -lt (($dataBytes + $pmBytes) * 1.3)) { Fail "not enough free space for the copy and some room to grow" }
if ($DryRun) { Write-Host "DRY RUN: would copy data and store as above into $Folder. Nothing was changed."; exit 0 }

$xd = @($Skip | ForEach-Object { Join-Path $WorkshopData $_ })
& robocopy $WorkshopData $appData /E /COPY:DAT /R:2 /W:2 /NFL /NDL /NJH /XD @xd /XF @SkipFiles | Out-Null
if ($LASTEXITCODE -ge 8) { Fail "copying the data failed (robocopy code $LASTEXITCODE)" }
if (-not $WithStore) { Write-Host "SEEDED: data $(GB (SizeOf $appData)) GB; no store copied (the app starts a fresh record). The workshop's copy is unchanged."; exit 0 }
& robocopy $WorkshopPm $appPm /E /COPY:DAT /R:2 /W:2 /NFL /NDL /NJH /XD (Join-Path $WorkshopPm "locks") | Out-Null
if ($LASTEXITCODE -ge 8) { Fail "copying the store failed (robocopy code $LASTEXITCODE)" }
if (-not (Test-Path (Join-Path $appPm "ledger.duckdb"))) { Fail "the store did not arrive" }
$a = (Get-FileHash (Join-Path $WorkshopPm "ledger.duckdb")).Hash
$b = (Get-FileHash (Join-Path $appPm "ledger.duckdb")).Hash
if ($a -ne $b) { Fail "the copied ledger is not identical to the workshop's" }
Write-Host "SEEDED: data $(GB (SizeOf $appData)) GB, store $(GB (SizeOf $appPm)) GB, ledger identical (SHA-256 $($b.Substring(0, 12))...). The workshop's copy is unchanged."
