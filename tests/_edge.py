"""Drive headless Edge over the DevTools protocol: load a URL, wait, optionally run JS, capture a screenshot, and report console errors."""
import asyncio, base64, json, os, socket, subprocess, tempfile, time, urllib.request
from pathlib import Path
import websockets

EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"


def _free():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p


async def _run(url, out, width, height, wait_s, steps, port):
    for _ in range(60):
        try:
            tabs = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{port}/json", timeout=2).read())
            tab = next(t for t in tabs if t["type"] == "page")
            break
        except Exception:
            await asyncio.sleep(0.5)
    else:
        raise RuntimeError("Edge did not start")
    errors, results = [], []
    async with websockets.connect(tab["webSocketDebuggerUrl"], max_size=64 * 1024 * 1024) as ws:
        n = 0
        async def send(method, **params):
            nonlocal n
            n += 1; i = n
            await ws.send(json.dumps({"id": i, "method": method, "params": params}))
            while True:
                m = json.loads(await ws.recv())
                if m.get("method") == "Runtime.exceptionThrown":
                    errors.append(m["params"]["exceptionDetails"].get("exception", {}).get("description", "exception")[:300])
                elif m.get("method") == "Runtime.consoleAPICalled" and m["params"]["type"] in ("error", "warning"):
                    errors.append(" ".join(str(a.get("value", a.get("description", ""))) for a in m["params"]["args"])[:300])
                elif m.get("id") == i:
                    return m.get("result", {})
        await send("Runtime.enable"); await send("Page.enable")
        await send("Emulation.setDeviceMetricsOverride", width=width, height=height, deviceScaleFactor=1, mobile=False)
        await send("Page.navigate", url=url)
        await asyncio.sleep(wait_s)
        for js, pause in steps:
            r = await send("Runtime.evaluate", expression=js, returnByValue=True, awaitPromise=True)
            results.append(r.get("result", {}).get("value"))
            await asyncio.sleep(pause)
        lay = await send("Page.getLayoutMetrics")
        h = int(min(lay["cssContentSize"]["height"], 4000))
        await send("Emulation.setDeviceMetricsOverride", width=width, height=max(h, height), deviceScaleFactor=1, mobile=False)
        await asyncio.sleep(0.4)
        shot = await send("Page.captureScreenshot", format="png")
        Path(out).write_bytes(base64.b64decode(shot["data"]))
    return errors, results


def shoot(url, out, width=1600, height=1000, wait_s=5, steps=()):
    port = _free()
    prof = tempfile.mkdtemp(prefix="edgecdp_")
    p = subprocess.Popen([EDGE, "--headless", "--disable-gpu", "--no-first-run", f"--remote-debugging-port={port}", f"--user-data-dir={prof}", "about:blank"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        return asyncio.run(_run(url, out, width, height, wait_s, steps, port))
    finally:
        # S79b: p.kill() ended only the main process; Edge's crashpad/gpu/renderer children lived on (550 of them, 32 GB, found overnight). Kill the whole tree and remove the profile.
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(p.pid)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            p.kill()
        except OSError:
            pass
        # a child that outlived its parent is no longer in the tree: find every process still carrying this run's own profile folder in its command line (the folder name is unique)
        subprocess.run(["powershell", "-NoProfile", "-Command",
                        f"Get-CimInstance Win32_Process | Where-Object {{ $_.CommandLine -like '*{os.path.basename(prof)}*' }} | ForEach-Object {{ Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }}"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60)
        import shutil
        shutil.rmtree(prof, ignore_errors=True)
