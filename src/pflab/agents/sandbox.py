"""Where the workshop's model-written code runs (S64 Phase 4). One interface, two ways to run it:

    Docker   `docker run --rm --network none --read-only --tmpfs /tmp --memory 2g --cpus 2 --pids-limit 256
             --security-opt no-new-privileges` on the image `pflab-sandbox:1` (sandbox/Dockerfile), the work folder
             mounted at /work. No network, no host files but that folder, killed at the time limit.
    Local    the previous way: a subprocess `python -I` with an emptied environment and a dead proxy. NOT a security
             boundary (the writers are our own models, not adversaries); used only when Docker is not available, and
             every such run is marked `contained: False`.

`pick()` takes Docker when `available()` says it works, else Local. OpenSandbox is not adopted (PLAN amendment, S64
Phase 4): it adds a server, and its fast microVM mode is Linux-only; our jobs are single-shot and `--network none` gives
the same isolation. This interface is where it would slot in later.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Callable, List, Optional

IMAGE = "pflab-sandbox:1"
RUNNER = Path(__file__).with_name("workshop_runner.py")
CACHE_S = 600                      # `available()` is remembered this long
PROBE_S = 5

_cache: dict = {"at": 0.0, "ok": False}


class Local:
    """Today's subprocess path, unchanged: `python -I` with only the system variables and a proxy that goes nowhere."""
    contained = False
    name = "local subprocess"

    def __init__(self, python: str = sys.executable, runner: Callable = subprocess.run):
        self.python, self._run = python, runner

    def run(self, work: Path, time_limit: int) -> subprocess.CompletedProcess:
        env = {k: v for k, v in os.environ.items() if k.upper() in ("SYSTEMROOT", "PATH", "TEMP", "TMP")}
        env.update({"HTTP_PROXY": "http://127.0.0.1:9", "HTTPS_PROXY": "http://127.0.0.1:9", "NO_PROXY": ""})
        return self._run([self.python, "-I", str(RUNNER), str(work)], cwd=str(work), env=env, capture_output=True,
                         timeout=time_limit)


class Docker:
    contained = True
    name = "Docker (no network, read-only root)"

    def __init__(self, runner: Callable = subprocess.run, image: str = IMAGE):
        self._run, self.image = runner, image

    def command(self, work: Path, name: str) -> List[str]:
        return ["docker", "run", "--rm", "--name", name, "--network", "none", "--read-only", "--tmpfs", "/tmp",
                "--memory", "2g", "--cpus", "2", "--pids-limit", "256", "--security-opt", "no-new-privileges",
                "-v", f"{work}:/work", "-w", "/work", self.image, "python", "-I", "/app/runner.py", "/work"]

    def run(self, work: Path, time_limit: int) -> subprocess.CompletedProcess:
        name = f"pflab-wk-{uuid.uuid4().hex[:12]}"
        try:
            return self._run(self.command(work, name), capture_output=True, timeout=time_limit + 20)
        except subprocess.TimeoutExpired:
            try:                                                   # the client is gone; the container may not be
                self._run(["docker", "kill", name], capture_output=True, timeout=15)
            except Exception:
                pass
            raise


def available(runner: Callable = subprocess.run, now: Optional[float] = None, force: bool = False) -> bool:
    """True when `docker info` answers within PROBE_S seconds and the image exists; remembered for CACHE_S seconds."""
    t = time.time() if now is None else now
    if not force and t - _cache["at"] < CACHE_S and _cache["at"]:
        return bool(_cache["ok"])
    ok = False
    try:
        info = runner(["docker", "info"], capture_output=True, timeout=PROBE_S)
        if info.returncode == 0:
            img = runner(["docker", "image", "inspect", IMAGE], capture_output=True, timeout=PROBE_S)
            ok = img.returncode == 0
    except Exception:
        ok = False
    _cache.update({"at": t, "ok": ok})
    return ok


def pick(python: str = sys.executable):
    """Docker when it works, else the local subprocess (marked uncontained by its `contained` flag).
    PFLAB_SANDBOX=local forces the subprocess (the test suite); =docker insists on Docker."""
    want = os.environ.get("PFLAB_SANDBOX", "").lower()
    if want == "local":
        return Local(python)
    return Docker() if (want == "docker" or available()) else Local(python)
