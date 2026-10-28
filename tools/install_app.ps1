<#
.SYNOPSIS
  Installs the Portfolio Lab APP from the private GitHub repo at a release tag, into its own folder (S65, docs/PLAN.md
  section 3). It never installs over an existing folder and never touches the workshop (D:\portfolio_lab).

.DESCRIPTION
  What it does, in order:  checks (folder empty, disk space, git, Python 3.13) -> sparse clone at the tag (only the files needed to
  run: no tests, no docs) -> .venv and `pip install -e .` -> data, pm and backups folders -> release.toml (channel stable; it
  sets this app's data and store folders and wins over any user-level PFLAB_DATA_DIR) -> the Docker sandbox image (if Docker is
  there) -> a start-up check -> the desktop shortcuts "Portfolio Lab" and "Portfolio Lab Update".
  The data is NOT copied here: tools\seed_app.ps1 does that once. The scheduled tick is registered only with -RegisterTick.

  Preview:   powershell -ExecutionPolicy Bypass -File tools\install_app.ps1 -DryRun
  Install:   powershell -ExecutionPolicy Bypass -File tools\install_app.ps1 [-Folder D:\PortfolioLabApp] [-Tag v2026.10.28]
  Duration:  3 to 6 minutes (the package install and, first time, the Docker image). Done when it prints "INSTALLED".
#>
[CmdletBinding()]
param(
  [string]$Folder = "D:\PortfolioLabApp",
  [string]$Repo = "",
  [string]$Tag = "",
  [switch]$DryRun,
  [switch]$RegisterTick,
  [switch]$NoDocker,
  [switch]$NoShortcut,
  [double]$MinFreeGB = 10
)
$ErrorActionPreference = "Stop"
$workshop = Split-Path -Parent $PSScriptRoot
$app = Join-Path $Folder "app"

function Step([string]$t) { Write-Host "== $t" }
function Act([string]$what, [scriptblock]$block) {
  if ($DryRun) { Write-Host "   would: $what" } else { Write-Host "   $what"; & $block }
}
function Fail([string]$m) { Write-Host "STOP: $m" -ForegroundColor Red; exit 1 }

Step "Checks"
if (-not $Repo) { $Repo = (& git -C $workshop remote get-url origin).Trim() }
if (-not $Repo) { Fail "no repo to install from: pass -Repo <url or path>" }
Write-Host "   repo: $Repo"
if ((Test-Path $Folder) -and (Get-ChildItem $Folder -Force -ErrorAction SilentlyContinue | Select-Object -First 1)) {
  Fail "$Folder already has files in it. An app is never installed over another folder; use 'pflab update' to update it."
}
$free = [math]::Round((Get-PSDrive ($Folder.Substring(0, 1))).Free / 1GB, 1)
Write-Host "   free space on $($Folder.Substring(0, 2)): $free GB (needs $MinFreeGB GB: about 5 GB of data and the store come later)"
if ($free -lt $MinFreeGB) { Fail "less than $MinFreeGB GB free on $($Folder.Substring(0, 2))" }
$longPaths = (Get-ItemProperty "HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem" -Name LongPathsEnabled -ErrorAction SilentlyContinue).LongPathsEnabled
if ($Folder.Length -gt 60 -and $longPaths -ne 1) {
  Fail "the folder path is $($Folder.Length) characters: Python packages nest deep and Windows stops at 260 without long paths. Choose a short folder (like D:\PortfolioLabApp) or enable long paths."
}
if (-not (Get-Command git -ErrorAction SilentlyContinue)) { Fail "git is not installed" }
$pyCmd = $null
foreach ($c in @("py -3.13", "python")) {
  $exe, $arg = $c -split " ", 2
  if (Get-Command $exe -ErrorAction SilentlyContinue) {
    $v = if ($arg) { & $exe $arg --version 2>&1 } else { & $exe --version 2>&1 }
    if ("$v" -match "Python 3\.13") { $pyCmd = $c; break }
  }
}
if (-not $pyCmd) { Fail "Python 3.13 is not installed (the libraries are pinned to it)" }
Write-Host "   python: $pyCmd"

if (-not $Tag) {
  $refs = & git ls-remote --tags --refs $Repo "v*" 2>$null | ForEach-Object { ($_ -split "refs/tags/")[1] }
  $good = @($refs | Where-Object { $_ -match '^v\d{4}\.\d{2}\.\d{2}(\.\d+)?$' })
  if (-not $good) { Fail "the repo has no release tag (vYYYY.MM.DD) yet: tag one in the workshop first" }
  $Tag = ($good | Sort-Object { [version]($_.Substring(1)) } -Descending | Select-Object -First 1)
}
Write-Host "   release: $Tag"

Step "Clone at the tag (only the files needed to run)"
Act "git clone --no-checkout $Repo $app" { New-Item -ItemType Directory -Force $Folder | Out-Null; & git clone --no-checkout $Repo $app; if ($LASTEXITCODE) { Fail "clone failed" } }
Act "sparse checkout without tests\ and docs\, then checkout $Tag" {
  & git -C $app sparse-checkout init --no-cone
  & git -C $app sparse-checkout set "/*" "!/tests/" "!/docs/"
  & git -C $app checkout --detach $Tag
  if ($LASTEXITCODE) { Fail "checkout of $Tag failed" }
}

Step "Python environment"
Act "create .venv and install the requirements" {
  Push-Location $app
  try {
    $exe, $arg = $pyCmd -split " ", 2
    if ($arg) { & $exe $arg -m venv .venv } else { & $exe -m venv .venv }
    & .\.venv\Scripts\python.exe -m pip install --quiet --upgrade pip
    & .\.venv\Scripts\python.exe -m pip install --quiet -e .
    if ($LASTEXITCODE) { Fail "pip install failed" }
  } finally { Pop-Location }
}

Step "Folders and the release file"
Act "create data, pm and backups under $Folder" { foreach ($d in "data", "pm", "backups") { New-Item -ItemType Directory -Force (Join-Path $Folder $d) | Out-Null } }
Act "write release.toml (channel stable, tag $Tag)" {
  & "$app\.venv\Scripts\python.exe" -W ignore -m pflab.release write --root $app --folder $Folder --tag $Tag --channel stable
  if ($LASTEXITCODE) { Fail "could not write release.toml" }
}

Step "Docker sandbox image (the workshop calculations run in it)"
if ($NoDocker -or -not (Get-Command docker -ErrorAction SilentlyContinue)) { Write-Host "   skipped (no Docker, or -NoDocker): calculations then run uncontained and the system says so" }
else {
  Act "docker build -t pflab-sandbox:1 (skipped if the image exists)" {
    & docker image inspect pflab-sandbox:1 *> $null
    if ($LASTEXITCODE) { Push-Location $app; try { & docker build -t pflab-sandbox:1 -f sandbox\Dockerfile . } finally { Pop-Location } }
  }
}

Step "Start-up check"
Act "python -m pflab.release show (the program starts and reads its release file)" {
  & "$app\.venv\Scripts\python.exe" -W ignore -m pflab.release show --root $app
  if ($LASTEXITCODE) { Fail "the program did not start" }
}

Step "Shortcuts"
if ($NoShortcut) { Write-Host "   skipped (-NoShortcut)" }
else {
  Act "desktop shortcuts 'Portfolio Lab' and 'Portfolio Lab Update' (they replace one of the same name)" {
    & powershell -ExecutionPolicy Bypass -File (Join-Path $app "tools\install_shortcut.ps1")
    $sh = New-Object -ComObject WScript.Shell
    $s = $sh.CreateShortcut((Join-Path ([Environment]::GetFolderPath("Desktop")) "Portfolio Lab Update.lnk"))
    $s.TargetPath = "powershell.exe"
    $s.Arguments = "-NoExit -ExecutionPolicy Bypass -Command `"& '$app\.venv\Scripts\python.exe' -m pflab.cli update`""
    $s.WorkingDirectory = $app
    $s.Description = "Portfolio Lab: update to the newest release (backs the store up first; close the app before)"
    $s.Save()
  }
}

Step "Scheduled tick"
if ($RegisterTick) { Act "register the tick (every 15 minutes, at logon, at wake)" { & powershell -ExecutionPolicy Bypass -File (Join-Path $app "tools\register_tasks.ps1") } }
else { Write-Host "   not registered. When the data is seeded and you are ready: powershell -ExecutionPolicy Bypass -File $app\tools\register_tasks.ps1" }

if ($DryRun) { Write-Host "DRY RUN: nothing was changed." } else { Write-Host "INSTALLED $Tag in $Folder. Next: tools\seed_app.ps1 (the one-time data copy)." }
