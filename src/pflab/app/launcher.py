"""Start the whole system from the desktop shortcut; closing the window stops it (S54, the investor 2026-10-22).

    .venv\\Scripts\\pythonw.exe -m pflab.app.launcher        (what the shortcut runs; no console)

One instance: a second double-click only opens the window again (waiting for a start still under way). The window is
Microsoft Edge in app mode with its own profile (no tabs, no address bar); it opens at once on a "starting" page that
switches to the dashboard when the server answers. The system stops when the window has been closed for IDLE_STOP_S
seconds, when Edge exits, or from the screen's power button; a running job gets up to JOB_GRACE_S to finish. A start-up
failure is logged and shown in a message box (pythonw has no console). Log: PFLAB_PM_DIR\\app\\app.log.

S65 (one desktop icon): an installed app takes the newest release tag before it starts (`pflab update` in a child process: the
store backed up first, a self-test, undone on a failure), then starts again on it. Offline, no newer tag, or the store held by
the tick: it starts as it is and tries at the next start.
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path
from typing import Optional

IDLE_STOP_S, JOB_GRACE_S, START_TIMEOUT_S = 20, 60, 60
UPDATE_EVERY_S, UPDATE_IDLE_S = 60, 30 * 60   # S58b: look for new code each minute; restart onto it after 30 min untouched
RESTART = 3                                    # _serve's return code: start again onto the new code
WINDOW_GONE_S = 10                             # no window connected this long, and Edge's process gone: stop
UPDATE_TIMEOUT_S = 15 * 60                     # S65: the update at start (fetch, install, self-test)
T0 = time.time()
EDGE = [Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Microsoft/Edge/Application/msedge.exe",
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Microsoft/Edge/Application/msedge.exe"]
STARTING = """<!doctype html><meta charset="utf-8"><title>Portfolio Lab</title>
<body style="margin:0;height:100vh;display:flex;align-items:center;justify-content:center;background:#0B0F14;color:#CBD5E1;
font:15px 'Segoe UI',system-ui,sans-serif"><div>Portfolio Lab is starting&hellip;</div>
<script>setInterval(function(){fetch("%sapi/health",{mode:"no-cors",cache:"no-store"}).then(function(){location.href="%s"},
function(){})},700)</script></body>"""


def open_window(url: str, profile: Path) -> Optional[subprocess.Popen]:
    edge = next((p for p in EDGE if p.exists()), None)
    if edge is None:
        webbrowser.open(url)
        return None
    profile.mkdir(parents=True, exist_ok=True)
    extra = ["--headless=new"] if os.environ.get("PFLAB_APP_HEADLESS") else []      # checks of the real start path only
    return subprocess.Popen([str(edge), *extra, f"--app={url}", f"--user-data-dir={profile}", "--no-first-run",
                             "--no-default-browser-check", "--start-maximized", "--disable-background-mode",
                             "--disable-features=msEdgeStartupBoost"])


DOCKER_DESKTOP = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Docker/Docker/Docker Desktop.exe"


def start_docker(log, exe: Path = DOCKER_DESKTOP, running=None, popen=subprocess.Popen) -> str:
    """S64: the workshop's sandbox needs Docker Desktop. Start it if it is installed and not running; do not wait for it
    (the workshop falls back to the local subprocess, marked uncontained, until it answers). Returns what happened."""
    if not exe.exists():
        return "not installed"
    if running is None:
        try:
            out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq Docker Desktop.exe", "/NH"], capture_output=True,
                                 text=True, timeout=10).stdout
            running = "Docker Desktop.exe" in out
        except Exception:
            running = False
    if running:
        return "already running"
    try:
        popen([str(exe)], close_fds=True, creationflags=0x00000008 if os.name == "nt" else 0)    # DETACHED_PROCESS
        log.info("started Docker Desktop for the workshop's sandbox")
        return "started"
    except OSError as e:
        log.warning("could not start Docker Desktop: %s", e)
        return f"failed: {e}"


def alert(text: str) -> None:
    """A message box: the only way a pythonw process can tell the investor something went wrong."""
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, text, "Portfolio Lab", 0x30 | 0x1000)       # warning icon, on top
    except Exception:
        pass


def why(e: BaseException) -> str:
    m = str(e)
    if "lock" in m.lower() or "being used by another process" in m.lower():
        return ("The ledger is open in another Portfolio Lab program (a pflab command, the Telegram bot or the night "
                "run). Close it, then double-click the shortcut again.")
    return f"Portfolio Lab could not start: {type(e).__name__}: {m[:300]}\n\nThe details are in pm\\app\\app.log."


def end_children_with_me():
    """Put this process in a Windows job object that ends every process it starts (job subprocesses such as the
    collector, the Edge window) when this process exits, so closing the system closes all of it. Returns the handle,
    which must stay open while the system runs; None off Windows or if Windows refuses."""
    try:
        import ctypes
        from ctypes import wintypes
    except ImportError:
        return None

    class Basic(ctypes.Structure):
        _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                    ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                    ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD), ("SchedulingClass", wintypes.DWORD)]

    class Io(ctypes.Structure):
        _fields_ = [(n, ctypes.c_uint64) for n in ("ReadOps", "WriteOps", "OtherOps", "ReadBytes", "WriteBytes",
                                                   "OtherBytes")]

    class Extended(ctypes.Structure):
        _fields_ = [("Basic", Basic), ("Io", Io), ("ProcessMemoryLimit", ctypes.c_size_t),
                    ("JobMemoryLimit", ctypes.c_size_t), ("PeakProcessMemoryUsed", ctypes.c_size_t),
                    ("PeakJobMemoryUsed", ctypes.c_size_t)]
    try:
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateJobObjectW.restype = wintypes.HANDLE
        k32.GetCurrentProcess.restype = wintypes.HANDLE
        job = k32.CreateJobObjectW(None, None)
        info = Extended()
        # KILL_ON_JOB_CLOSE; BREAKAWAY_OK lets only the restart (started with CREATE_BREAKAWAY_FROM_JOB) outlive us
        info.Basic.LimitFlags = 0x2000 | 0x800
        ok = (k32.SetInformationJobObject(wintypes.HANDLE(job), 9, ctypes.byref(info), ctypes.sizeof(info))
              and k32.AssignProcessToJobObject(wintypes.HANDLE(job), wintypes.HANDLE(k32.GetCurrentProcess())))
        return job if job and ok else None
    except (AttributeError, OSError):
        return None


def update_first(log, run=subprocess.run) -> Optional[str]:
    """S65: an installed app takes the newest release before it starts. Returns the new tag, or None (the workshop, no newer tag,
    offline, the store held by the tick, a failed update that undid itself: it starts as it is)."""
    from pflab import release
    before = release.load(release.ROOT)
    if before is None:
        return None
    py = Path(sys.executable).with_name("python.exe")    # the console interpreter beside pythonw: pip and git run there
    try:
        p = run([str(py if py.exists() else sys.executable), "-m", "pflab.cli", "update"], cwd=str(release.ROOT), capture_output=True,
                text=True, timeout=UPDATE_TIMEOUT_S, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.SubprocessError) as e:
        log.warning("update at start skipped: %s", e)
        return None
    log.info("update at start (rc %s): %s", p.returncode, ((p.stdout or "") + (p.stderr or "")).strip()[-400:])
    old = (before.get("app") or {}).get("tag")
    new = ((release.load(release.ROOT) or {}).get("app") or {}).get("tag")
    return new if new and new != old else None


def _up(url: str) -> bool:
    try:
        with urllib.request.urlopen(url + "api/health", timeout=2) as r:
            return r.status == 200
    except Exception:
        return False


def main() -> int:
    from pflab.pm import store
    pm = store.pm_dir()
    (pm / "app").mkdir(parents=True, exist_ok=True)
    logging.basicConfig(filename=pm / "app" / "app.log", level=logging.INFO, encoding="utf-8",
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    log = logging.getLogger("pflab.app")
    if sys.stdout is None or sys.stderr is None:          # pythonw: anything printed goes to the log, not into the void
        sys.stdout = sys.stderr = open(pm / "app" / "app.log", "a", encoding="utf-8", buffering=1)
    if "--after" in sys.argv:                              # a restart: the old instance first lets go of the ledger
        from pflab._lock import _alive
        old = sys.argv[sys.argv.index("--after") + 1]
        t0 = time.time()
        while _alive(old) and time.time() - t0 < JOB_GRACE_S + 30:
            time.sleep(0.5)
        log.info("restarting onto the new code (the old instance %s has stopped)", old)
    try:
        return _run(pm, log)
    except Exception as e:
        log.exception("start failed")
        alert(why(e))
        return 1


def restart(log) -> None:
    """Start a new instance outside this one's job object (which ends everything else with us), then let this one end."""
    flags = 0x00000008 | 0x01000000 | 0x00000200            # DETACHED_PROCESS | CREATE_BREAKAWAY_FROM_JOB | NEW_GROUP
    cmd = [sys.executable, "-m", "pflab.app.launcher", "--after", str(os.getpid())]
    try:
        subprocess.Popen(cmd, cwd=str(Path(__file__).resolve().parents[3]), creationflags=flags if os.name == "nt" else 0,
                         close_fds=True)
        log.info("restart started")
    except OSError as e:
        log.exception("restart failed")
        alert(f"Portfolio Lab stopped for an update but could not start again by itself ({e}). Double-click the "
              "shortcut to start it.")


def _run(pm: Path, log) -> int:
    from pflab._lock import FileLock, LockBusy
    from pflab.app import settings as st
    port = st.load(pm)["port"]
    url = f"http://127.0.0.1:{port}/"
    profile = pm / "app" / "edge-profile"
    try:
        lock = FileLock(pm / "app" / "app.lock", name="dashboard").__enter__()
    except LockBusy:
        log.info("already running: opening the window")
        t0 = time.time()
        while not _up(url):                                # the first double-click may still be starting
            if time.time() - t0 > START_TIMEOUT_S:
                alert("Portfolio Lab is already running but its screen does not answer. End pythonw.exe in Task "
                      "Manager, then start it again.")
                return 1
            time.sleep(0.5)
        open_window(url, profile)
        return 0
    start_docker(log)                                      # the workshop's sandbox; not waited for
    job = end_children_with_me()                           # kept open until this process exits
    log.info("children end with the system: %s", "yes" if job else "NO (Windows refused the job object)")
    starting = pm / "app" / "starting.html"
    starting.write_text(STARTING % (url, url), encoding="utf-8")
    win = open_window(starting.as_uri(), profile)          # at once: the imports below take a few seconds
    new = update_first(log)                                # S65: the one icon also updates
    if new:
        log.info("updated to %s at start: starting again on it", new)
        if win is not None:
            win.terminate()
        close_window(profile)
        lock.__exit__(None, None, None)
        restart(log)
        return 0
    try:
        rc = _serve(pm, log, url, port, win)
    except BaseException:
        if win is not None:
            win.terminate()
        raise
    finally:
        lock.__exit__(None, None, None)
    if rc == RESTART:
        restart(log)
        return 0
    return rc


def _serve(pm: Path, log, url: str, port: int, win) -> int:
    import uvicorn

    from pflab.app.runtime import Runtime
    from pflab.app.server import create_app
    from pflab.data import data_dir
    from pflab.pm import secrets as sec
    try:
        secrets = sec.load()
    except sec.SecretsError:
        secrets = None
    repo = Path(__file__).resolve().parents[3]
    rt = Runtime(pm, data_dir(), repo, secrets=secrets)
    app = create_app(rt)
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", access_log=False))
    th = threading.Thread(target=server.run, name="server", daemon=True)
    th.start()
    t0 = time.time()
    while not _up(url):
        if time.time() - t0 > START_TIMEOUT_S or not th.is_alive():
            rt.con.close()
            raise RuntimeError(f"the screen's server did not start on port {port} (another program may be using it)")
        time.sleep(0.3)
    rt.start()
    log.info("system started on %s in %.1f s", url, time.time() - T0)
    rc, looked = 0, time.time()
    try:
        while True:
            time.sleep(2)
            if app.state.restart_requested.is_set():
                log.info("restart requested from the screen")
                rc = RESTART
                break
            if app.state.shutdown_requested.is_set():
                log.info("stop requested from the screen")
                break
            if time.time() - looked > UPDATE_EVERY_S:
                looked = time.time()
                if rt.check_update() and rt.quiet() and (rt.clock() - rt.last_seen).total_seconds() > UPDATE_IDLE_S:
                    log.info("update ready, nothing running, the window untouched for %d min: restarting",
                             UPDATE_IDLE_S // 60)
                    rc = RESTART
                    break
            if rt.idle_for() > IDLE_STOP_S:
                log.info("window closed: stopping")
                break
            # S59: 10 s, not 3 (a dropped event stream reconnects after about 3 s; 2026-10-24 18:32 the system stopped 16 s
            # after a start with the window still wanted); the page now reconnects after 1 s
            if win is not None and win.poll() is not None and rt.idle_for() > WINDOW_GONE_S:
                log.info("Edge exited: stopping")
                break
    finally:
        rt.shutdown(JOB_GRACE_S)
        server.should_exit = True
        th.join(10)
        try:
            rt.con.close()
        except Exception:
            pass
        close_window(pm / "app" / "edge-profile")
        log.info("system stopped")
    return rc


def close_window(profile: Path) -> None:
    """End the dashboard's Edge window (Edge restarts itself outside the job object, so it is found by its profile)."""
    cmd = ("Get-CimInstance Win32_Process -Filter \"Name='msedge.exe'\" | Where-Object { $_.CommandLine -like "
           f"'*{profile}*' }} | ForEach-Object {{ Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }}")
    try:
        subprocess.run(["powershell", "-NoProfile", "-Command", cmd], timeout=20, capture_output=True,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.SubprocessError):
        pass


if __name__ == "__main__":
    sys.exit(main())
