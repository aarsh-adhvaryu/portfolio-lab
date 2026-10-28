# Overnight run, unattended: data, the system's jobs, research (deep notes by the API analyst), S45/S46 studies, S47
# tuning, S49 memory comparison, then a morning report.
#
#   cd D:\portfolio_lab
#   powershell -ExecutionPolicy Bypass -File tools\overnight.ps1 -DeepAll   # everything; deep notes on every list name
#   powershell -ExecutionPolicy Bypass -File tools\overnight.ps1            # deep notes only where something changed
#   powershell -ExecutionPolicy Bypass -File tools\overnight.ps1 -DryRun    # check prerequisites, print the steps
#   powershell -ExecutionPolicy Bypass -File tools\overnight.ps1 -Phases report   # only the morning report
#   add -QloraData to also generate S47 pass-2 training data until done (-QloraHours N caps it; it resumes)
#
# Built to run with nobody watching and a network that may drop:
#   - every step is its own process with a time limit: a step that hangs is stopped (with its children) and the run goes on
#   - steps that need the internet run first, each checks the connection and is skipped at once when offline
#   - failed or skipped internet steps are tried once more at the end; everything else runs offline
#     (both local models are on disk; nothing is downloaded unless a model is missing)
#   - the laptop is kept awake; nothing is sent to Telegram (held alerts stay held)
# The report: PFLAB_PM_DIR\reports\morning_<date>.md (personal: stays out of git). Done when the log says FINISHED;
# PFLAB_PM_DIR\reports\overnight_<date>.status lists every step's outcome.

param([switch]$DryRun, [switch]$DeepAll, [switch]$QloraData, [int]$QloraHours = 24,
      # tuning (S47 pass 1) and memory (S49) were decided 2026-10-18: not re-run nightly (their test sets are spent);
      # run them by name (-Phases tuning,memory) only under a new registration
      [string[]]$Phases = @("checks", "tests", "data", "jobs", "research", "deep", "studies", "collect", "report"))

$ErrorActionPreference = "Continue"
$Phases = @($Phases | ForEach-Object { $_ -split "," } | ForEach-Object { $_.Trim() } | Where-Object { $_ })   # -File passes "a,b" as one string
Set-Location (Split-Path $PSScriptRoot -Parent)
$env:PYTHONIOENCODING = "utf-8"
$py = (Resolve-Path ".venv\Scripts\python.exe").Path
# S65: an installed app has release.toml at its root: it sets the data and store folders and wins over the environment
# (a user-level PFLAB_DATA_DIR may still point at the workshop). Without it this is the workshop, where outward sends and paid
# calls are blocked by src\pflab\guard.py.
$rel = Join-Path (Get-Location) "release.toml"
$isApp = Test-Path $rel
if ($isApp) {
    foreach ($kv in @(@("data", "PFLAB_DATA_DIR"), @("pm", "PFLAB_PM_DIR"))) {
        $m = Select-String -Path $rel -Pattern ("^" + $kv[0] + " = '(.+)'\s*$") | Select-Object -First 1
        if ($m) { Set-Item -Path ("Env:" + $kv[1]) -Value $m.Matches[0].Groups[1].Value }
    }
}
$pm = if ($env:PFLAB_PM_DIR) { $env:PFLAB_PM_DIR } else { "D:\portfolio_lab\pm" }
$day = Get-Date -Format "yyyy-MM-dd"
New-Item -ItemType Directory -Force "$pm\reports" | Out-Null
$log = "$pm\reports\overnight_$day.log"
$statusFile = "$pm\reports\overnight_$day.status"
$report = "$pm\reports\morning_$day.md"
$tmp = "$pm\reports\_step"
$status = [ordered]@{}
$retry = New-Object System.Collections.ArrayList
# any unexpected script error is logged and the run goes on with the next step (nobody is watching)
trap { Add-Content -Path $log -Value ("{0}  SCRIPT ERROR (run continues): {1}" -f (Get-Date -Format "HH:mm:ss"), $_) -Encoding utf8; continue }

function Log($msg) {
    $line = "{0}  {1}" -f (Get-Date -Format "HH:mm:ss"), $msg
    Write-Host $line
    Add-Content -Path $log -Value $line -Encoding utf8
}

function Online {
    try {
        $c = New-Object System.Net.Sockets.TcpClient
        $ok = $c.ConnectAsync("www.bseindia.com", 443).Wait(5000) -and $c.Connected
        $c.Close(); return $ok
    } catch { return $false }
}

function Quote([string]$a) { if ($a -match '[\s"]') { '"' + ($a -replace '"', '\"') + '"' } else { $a } }

# Run one python step with a time limit. Returns its output; records ok / FAILED / TIMEOUT / SKIPPED.
function Run($name, [int]$minutes, [bool]$net, [string[]]$argv, [switch]$Quiet) {
    if ($DryRun) { Log "would run: $name (limit $minutes min$(if ($net) { ', needs internet' }))"; return "" }
    if ($net -and -not (Online)) {
        $status[$name] = "SKIPPED: offline"; Log "SKIP $name (offline)"
        [void]$retry.Add(@($name, $minutes, $argv)); return ""
    }
    if (-not $Quiet) { Log "START $name" }
    $t0 = Get-Date
    Remove-Item "$tmp.out", "$tmp.err" -ErrorAction SilentlyContinue
    $p = Start-Process -FilePath $py -ArgumentList (($argv | ForEach-Object { Quote $_ }) -join " ") -NoNewWindow -PassThru `
        -RedirectStandardOutput "$tmp.out" -RedirectStandardError "$tmp.err"
    $null = $p.Handle
    $done = $p.WaitForExit($minutes * 60 * 1000)
    if (-not $done) { & taskkill /T /F /PID $p.Id *> $null; Start-Sleep -Seconds 2 }
    # python writes UTF-8 (PYTHONIOENCODING); PowerShell 5.1 would read a file without a BOM as ANSI (Rs sign garbled)
    $out = ((Get-Content "$tmp.out" -Raw -Encoding UTF8 -ErrorAction SilentlyContinue) + (Get-Content "$tmp.err" -Raw -Encoding UTF8 -ErrorAction SilentlyContinue))
    if ($null -eq $out) { $out = "" }
    $mins = [math]::Round(((Get-Date) - $t0).TotalMinutes, 1)
    if (-not $Quiet) {
        Add-Content -Path $log -Value $out -Encoding utf8
        if (-not $done) { $st = "TIMEOUT after $minutes min (stopped)" }
        elseif ($p.ExitCode -ne 0 -or $out -match "Traceback \(most recent call last\)") { $st = "FAILED (exit $($p.ExitCode), $mins min): see log" }
        else { $st = "ok ($mins min)" }
        $status[$name] = $st
        Log "END ${name}: $st"
        if ($net -and $st -notlike "ok*") { [void]$retry.Add(@($name, $minutes, $argv)) }
    }
    return $out
}

function PfCli($name, $minutes, $net, [string]$line) { Run $name $minutes $net (@("-m", "pflab.cli") + ($line -split " ")) | Out-Null }

Add-Type -Namespace PfLabN -Name Power -MemberDefinition '[DllImport("kernel32.dll")] public static extern uint SetThreadExecutionState(uint esFlags);'
[PfLabN.Power]::SetThreadExecutionState([uint32]"0x80000001") | Out-Null      # stay awake while this runs

try {
    Log "overnight run $day; phases: $($Phases -join ', ')$(if ($DeepAll) { '; deep notes on every list name' })$(if ($DryRun) { ' (DRY RUN)' })"

    if ($Phases -contains "checks") {
        $problems = @()
        & ollama list *> $null; if ($LASTEXITCODE -ne 0) { $problems += "Ollama is not running (open the Ollama app)" }
        if (-not (Online)) { $problems += "offline now: internet steps will be skipped and retried at the end" }
        $bat = Get-CimInstance Win32_Battery -ErrorAction SilentlyContinue
        if ($bat -and $bat.BatteryStatus -ne 2) { $problems += "on battery: plug the laptop in" }
        $busy = Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" | Where-Object { $_.CommandLine -match 'pflab\.(cli|app)' }
        if ($busy) { $problems += "another pflab process holds the ledger (pid $($busy.ProcessId -join ', ')): close it (the dashboard: close its window)" }
        $free = [math]::Round((Get-PSDrive D).Free / 1GB, 1)
        if ($free -lt 10) { $problems += "only $free GB free on D:" }
        $have = (& ollama list 2>$null | Out-String)
        foreach ($m in @("qwen3:8b-q8_0", "nomic-embed-text")) {
            if ($have -notmatch [regex]::Escape($m)) {
                if ($DryRun) { $problems += "model $m missing (the run would download it once)" }
                else { Log "downloading $m once"; & ollama pull $m *>> $log }
            }
        }
        $status["checks"] = $(if ($problems) { "NOTE: " + ($problems -join "; ") } else { "ok ($free GB free; models on disk)" })
        Log "checks: $($status['checks'])"
    }

    if ($Phases -contains "selftest") {           # not in the default phases: proves a hung step is stopped
        Run "selftest: a step that hangs" 0 $false @("-c", "import time; time.sleep(120)") | Out-Null
        Run "selftest: a step that fails" 1 $false @("-c", "raise SystemExit(3)") | Out-Null
    }

    if ($Phases -contains "tests") { Run "tests (full suite)" 25 $false @("-m", "pytest", "-q", "-p", "no:cacheprovider") | Out-Null }

    # ---- internet first ----------------------------------------------------------------------------------------
    if ($Phases -contains "data") {
        Run "collect market data (5 days)" 45 $true @("tools\collect_daily.py", "--days", "5", "--sources", "bhavcopy,corporate_actions,dividends,bse_bhavcopy,surveillance,indices,vix,bse") | Out-Null
        Run "collect news (GDELT GKG, 3 days)" 120 $true @("tools\collect_daily.py", "--days", "3", "--sources", "gkg") | Out-Null
    }
    if ($Phases -contains "jobs") {
        PfCli "system job: prices" 20 $false "service run prices"
        PfCli "system job: nav" 20 $true "service run nav"
        PfCli "system job: filings" 30 $true "service run filings"
        PfCli "system job: guards" 30 $true "service run guards"
        PfCli "system job: global (world markets, US VIX)" 20 $true "service run global"
        PfCli "system job: kg" 60 $false "service run kg"
        PfCli "knowledge graph with news since $((Get-Date).AddDays(-7).ToString('yyyy-MM-dd'))" 60 $false "kg build --gkg-since $((Get-Date).AddDays(-7).ToString('yyyy-MM-dd'))"
        PfCli "article text (where robots.txt allows)" 45 $true "kg text --limit 200"
        # S64: price ranges by calibrated statistics, the baselines and the scoring (before the researcher)
        PfCli "forecasts: price ranges, turnover and results; scoring" 30 $false "forecast run"
    }
    if ($Phases -contains "research") {
        PfCli "inbox: dropped files into the graph" 20 $false "inbox"
        PfCli "S49 look-up index (new items only)" 30 $false "memory index"
        PfCli "researcher: changes and briefs" 60 $false "research run"
    }
    if ($Phases -contains "deep") {
        if ($DeepAll) { PfCli "deep research: queue every list name" 20 $true "research deep --all" }
        else { PfCli "deep research: queue names with changes" 20 $true "research deep" }
        PfCli "deep research: submit the batch (half price)" 10 $true "analyst submit"
    }

    # ---- offline: local models and data on disk ----------------------------------------------------------------
    if ($Phases -contains "studies") {
        Run "S45 split / limit study (pre-registered)" 30 $false @("tools\split_study.py") | Out-Null
        PfCli "S46 drift checks of the adopted rules" 10 $false "drift"
        PfCli "S46 theses: evidence, exposure, action cost" 20 $false "thesis update"
    }
    if ($Phases -contains "tuning") {
        PfCli "S47 tuning: materiality" 90 $false "llm tune materiality"
        PfCli "S47 tuning: routing" 90 $false "llm tune routing"
        PfCli "S47 tuning: writing" 240 $false "llm tune writing"
        PfCli "S47 tuning: research" 300 $false "llm tune research"
    }
    if ($Phases -contains "memory") { PfCli "S49 memory retrieval: words vs embeddings (pre-registered)" 120 $false "memory compare" }
    # S47 pass 2 training data (docs/llm/qlora_s47_pass2_protocol.md): opt-in; runs until every task is done (limit
    # -QloraHours, default 24: in practice none; about 23 s a task); a stopped run resumes where it stopped
    if ($QloraData) { PfCli "S47 pass 2: training data (rejection sampling, resumes)" ($QloraHours * 60) $false "llm qlora data" }

    # ---- internet again: the analyst's batch, then briefs written from it --------------------------------------
    if ($Phases -contains "collect") {
        PfCli "deep research: collect the batch (waits up to 3 hours)" 200 $true "analyst collect --wait 180"
        PfCli "researcher: rewrite briefs from the analyst notes" 90 $false "research run --rebrief"
    }
    if ($retry.Count -and -not $DryRun) {
        Log "retrying $($retry.Count) internet step(s) once"
        foreach ($r in @($retry)) { if ($status[$r[0]] -notlike "ok*") { Run ("retry: " + $r[0]) $r[1] $true $r[2] | Out-Null } }
    }

    if ($Phases -contains "report" -and -not $DryRun) {
        Log "writing $report"
        $sections = [ordered]@{
            "Research: what changed (last 24 hours)"          = @(10, "research digest --hours 24")
            "Deep research notes (API analyst)"               = @(10, "analyst notes --hours 24")
            "Your theses"                                     = @(20, "thesis show")
            "Next FD tranche: what to buy and how (S45; a proposal, not an order)" = @(20, "pm advise")
            "Split / limit study (S45)"                       = @(5, "studies split")
            "Drift checks of adopted rules (S46)"             = @(10, "drift")
            "Memory retrieval comparison (S49)"               = @(5, "studies memory")
            "S47 tuning results"                              = @(5, "llm tune report")
            "Forecasts (S52: turnover, results ranges; scoreboard)" = @(5, "forecast show")
            "Market state, dip rule and guards"               = @(20, "pm guards --no-alerts")
            "Net worth"                                       = @(10, "pm networth")
            "This month's proposal (not logged)"              = @(10, "pm propose --amount 0 --no-log")
            "Deployment of FD maturities"                     = @(10, "pm deploy")
            "Risk (Monte Carlo)"                              = @(20, "pm simulate --paths 5000")
            "Questions for you"                               = @(5, "questions")
            "API spend"                                       = @(5, "analyst spend")
            "Alerts waiting (NOT sent)"                       = @(5, "pm alerts")
            "System health"                                   = @(5, "service status")
        }
        $md = @("# Morning report $day", "", "Steps:", "")
        foreach ($k in $status.Keys) { $md += "- ${k}: $($status[$k])" }
        foreach ($title in $sections.Keys) {
            $s = $sections[$title]
            $out = Run $title $s[0] $false (@("-m", "pflab.cli") + ($s[1] -split " ")) -Quiet
            if ($title -like "Deep research notes*") { $md += @("", "## $title", "", $out.TrimEnd()) }
            else { $md += @("", "## $title", "", '```', $out.TrimEnd(), '```') }
        }
        Set-Content -Path $report -Value $md -Encoding utf8
        Log "report written"
    }
    if (-not $DryRun) { $status.GetEnumerator() | ForEach-Object { "{0}: {1}" -f $_.Key, $_.Value } | Set-Content $statusFile -Encoding utf8 }
    Log "FINISHED"
}
finally {
    Remove-Item "$tmp.out", "$tmp.err" -ErrorAction SilentlyContinue
    [PfLabN.Power]::SetThreadExecutionState([uint32]"0x80000000") | Out-Null
}
