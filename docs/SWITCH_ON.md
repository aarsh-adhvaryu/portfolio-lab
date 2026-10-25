# Switch-on checklist (The investor's steps, in order; nothing here is run by Claude)

Rewritten 2026-10-24 (S58b) for the system as it now runs: the dashboard runs every job while its window is open; a
scheduled task runs them when it is closed (it stands aside while the dashboard is open); the dashboard's Settings
decide for both (the preset, and whether held Telegram messages are sent). Each step is reversible; the undo is given.
Run commands from `D:\portfolio_lab` in PowerShell, with the dashboard CLOSED unless a step says otherwise (only one
program may hold the ledger).

1. **Restart onto the new code.** Close the dashboard window, or use the power button at the top right ("Stop the
   system"), and wait ten seconds; `Get-Process pythonw -ErrorAction SilentlyContinue` should show nothing from
   portfolio_lab. Double-click "Portfolio Lab". On the Schedule screen press Run on `kg` and `plans`: your answers of
   24 Oct (the Gadget Co name, the monthly amount) are applied by those two jobs.
2. **Backup target. DECIDED 2026-10-24: none for now** (The investor: "if I need one I will tell you"; recorded as
   `[backup] declined` in `configs/service.toml`, shown as off, never asked). When wanted: pick an external drive or a
   synced folder (OneDrive or Google Drive for desktop), then set it once:
   `[Environment]::SetEnvironmentVariable("PFLAB_BACKUP_DIR", "E:\pflab-backup", "User")` (your path), and restart the
   dashboard (step 1). The nightly backup turns on by itself; the question closes by itself.
   Undo: `[Environment]::SetEnvironmentVariable("PFLAB_BACKUP_DIR", $null, "User")`.
3. **Telegram.** a) In `%USERPROFILE%\.pflab\secrets.toml`, `[telegram]` needs `token` (from BotFather) and `chat_id`
   (your chat); `.venv\Scripts\python -m pflab.cli service status` shows "telegram config" OK when both are there.
   b) Look at what is held: `.venv\Scripts\python -m pflab.cli pm alerts`. Drop the stale ones (the restart drills
   queued several): `.venv\Scripts\python -m pflab.cli pm alerts --drop-before 2026-10-24` (they are kept, marked
   dropped, never sent). c) Test: `.venv\Scripts\python -m pflab.cli service test-alert` (one message to your chat).
   d) Dashboard -> Settings -> "Send Telegram messages" on. From then on messages go out, window open or not.
   Undo: the same switch off (messages are held again).
4. **The scheduled task** (one entry: every 15 minutes, at logon and on wake; no admin rights; no window):
   preview `.\tools\register_tasks.ps1 -WhatIf`, then `.\tools\register_tasks.ps1`.
   While the dashboard is open the task does nothing (the dashboard runs the jobs); closed, it runs what is due:
   collect 19:30, prices 20:15, guards 20:45, plans 21:30, nav 22:45, kg 23:00, research 23:30, analyst 01:00,
   filings hourly, the trade check hourly 08-22 when Kite is logged in, world markets 07:30, backup 23:30, the
   conductor every 15 minutes (its asks and notes). Check: `Get-Content pm\reports\tick.log -Tail 20` after a closed
   quarter-hour. Opening the dashboard while a night job holds the ledger shows "the ledger is open in another
   Portfolio Lab program": wait for the job to finish (the collector's news can take half an hour).
   Undo: `Unregister-ScheduledTask -TaskName "PFLab Tick" -Confirm:$false`.
5. **Kite, each trading morning.** The "Log in to Kite" button at the top of the dashboard (or
   `.venv\Scripts\python tools\kite_login.py`); the token lasts until about 06:00 the next day. From 08:30 on a trading
   day the system asks for it. The snapshot is taken at once and every hour after: the portfolio today.
6. **Statements, each month.** From the 3rd, the system asks for last month's Zerodha funds statement and tradebook,
   the bank statements and the CAS: drop them in Inbox and files, press "Add to the ledger" after its checks pass.
7. **Optional.** A weekly deep sweep: `powershell -ExecutionPolicy Bypass -File tools\overnight.ps1 -DeepAll` with the
   dashboard closed (its report in `pm\reports` says when it finished). The two-way Telegram bot (`.venv\Scripts\python -m pflab.cli bot run`) also
   holds the ledger, so it runs only while the dashboard is closed.
8. **API cap** stays ₹1,500 a month (`PFLAB_PM_DIR\api_budget.toml`); every Opus call is priced against it first.
