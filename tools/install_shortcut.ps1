# S54: put "Portfolio Lab" on the desktop. Double-click starts the whole system (screen, jobs, live prices) in one
# process; closing the window stops it. Run once from D:\portfolio_lab:
#   powershell -ExecutionPolicy Bypass -File tools\install_shortcut.ps1
$repo = Split-Path $PSScriptRoot -Parent
$pyw = Join-Path $repo ".venv\Scripts\pythonw.exe"
$ico = Join-Path $repo "src\pflab\app\static\pflab.ico"
if (-not (Test-Path $pyw)) { Write-Error "missing $pyw"; exit 1 }
$desktop = [Environment]::GetFolderPath("Desktop")
$lnk = Join-Path $desktop "Portfolio Lab.lnk"
$sh = New-Object -ComObject WScript.Shell
$s = $sh.CreateShortcut($lnk)
$s.TargetPath = $pyw
$s.Arguments = "-m pflab.app.launcher"
$s.WorkingDirectory = $repo
if (Test-Path $ico) { $s.IconLocation = "$ico,0" }
$s.Description = "Portfolio Lab: start the system; close the window to stop it"
$s.WindowStyle = 1
$s.Save()
Write-Output "shortcut: $lnk"
