"""Where the workshop's model-written code runs (S64 Phase 4; S67 fail-closed). One interface:

    Docker   `docker run --rm --network none --read-only --tmpfs /tmp --memory 2g --memory-swap 2g --cpus 2 --pids-limit 256
             --cap-drop ALL --security-opt no-new-privileges` on the image `pflab-sandbox:2` (sandbox/Dockerfile). The job folder is
             mounted READ-ONLY at /work and a separate empty folder at /out (the only place the run can write, read back at most
             MAX_OUT bytes); no network, no other host files, killed at the time limit (`docker kill` if the client is gone).
    Local    a subprocess `python -I` with an emptied environment: NOT a security boundary. It exists for the test suite and for the
             developer's workshop, and only when asked for by name (`PFLAB_SANDBOX=local`); an installed app (a `release.toml`)
             refuses it. It is never chosen because Docker is missing.

`pick()` returns Docker when `status()` says it works, else raises `SandboxUnavailable` saying what is missing: the calculation then
does not run (the caller waits for the sandbox and asks him once). Containment is proven, not assumed: `probe()` runs a short script
inside a container with the same flags and checks that the network is closed, the root and the job folder cannot be written, no host
path or secret is visible, and a run past its limit is killed (`pflab verify` runs it on his PC).

OpenSandbox is not adopted: it adds a server, and our jobs are single-shot; this interface is where it would slot in.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path
from typing import Callable, List, Optional

IMAGE = "pflab-sandbox:2"
RUNNER = Path(__file__).with_name("workshop_runner.py")
CACHE_S = 600                      # `available()` is remembered this long
PROBE_S = 5
MAX_OUT = 1_000_000                # bytes of out.json read back from a run

_cache: dict = {"at": 0.0, "ok": False, "why": ""}


def read_result(path: Path, limit: int = MAX_OUT) -> dict:
    """The one file a run hands back, read defensively: a link or reparse point or any non-regular file is refused (a run could point it
    at a host file), at most `limit` bytes are read (never the whole file first), and it must be a JSON object. Anything else becomes
    {"error": why}, which the caller reports as a failed run: nothing is guessed from a damaged result."""
    path = Path(path)
    try:
        st = path.lstat()
    except OSError:
        return {}
    import stat
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISREG(st.st_mode) or getattr(st, "st_file_attributes", 0) & 0x400:
        return {"error": "the run's result was not a plain file and was refused"}
    if st.st_size > limit:
        return {"error": f"the run's result is larger than {limit} bytes and was refused"}
    try:
        with open(path, "rb") as fh:
            data = fh.read(limit + 1)
        if len(data) > limit:
            return {"error": f"the run's result is larger than {limit} bytes and was refused"}
        obj = json.loads(data.decode("utf-8"))
    except (OSError, ValueError):
        return {"error": "the run's result was not valid JSON and was refused"}
    if not isinstance(obj, dict) or not all(isinstance(k, str) for k in obj):
        return {"error": "the run's result was not a JSON object and was refused"}
    return obj


class SandboxUnavailable(RuntimeError):
    """The contained sandbox cannot run now. Nothing was executed."""


class Local:
    """The subprocess path: `python -I` with only the system variables and a proxy that goes nowhere. Not contained."""
    contained = False
    name = "local subprocess (NOT contained)"

    def __init__(self, python: str = sys.executable, runner: Callable = subprocess.run):
        self.python, self._run = python, runner

    def run(self, work: Path, time_limit: int) -> subprocess.CompletedProcess:
        env = {k: v for k, v in os.environ.items() if k.upper() in ("SYSTEMROOT", "PATH", "TEMP", "TMP")}
        env.update({"HTTP_PROXY": "http://127.0.0.1:9", "HTTPS_PROXY": "http://127.0.0.1:9", "NO_PROXY": ""})
        return self._run([self.python, "-I", str(RUNNER), str(work)], cwd=str(work), env=env, capture_output=True,
                         timeout=time_limit)


def _flags(name: str, work: Optional[Path] = None, out: Optional[Path] = None) -> List[str]:
    cmd = ["docker", "run", "--rm", "--name", name, "--network", "none", "--read-only", "--tmpfs", "/tmp:rw,size=256m",
           "--memory", "2g", "--memory-swap", "2g", "--cpus", "2", "--pids-limit", "256", "--cap-drop", "ALL", "--ipc", "none",
           "--ulimit", "nofile=256:256", "--ulimit", "core=0", "--security-opt", "no-new-privileges"]
    if work is not None:
        cmd += ["-v", f"{work}:/work:ro"]
    if out is not None:
        cmd += ["-v", f"{out}:/out", "-e", "PFLAB_OUT=/out"]
    return cmd + ["-w", "/work" if work is not None else "/tmp"]


class Docker:
    contained = True
    name = "Docker (no network, read-only root, job folder read-only)"

    def __init__(self, runner: Callable = subprocess.run, image: str = IMAGE):
        self._run, self.image = runner, image

    def command(self, work: Path, name: str, out: Path) -> List[str]:
        return _flags(name, work, out) + [self.image, "python", "-I", "/app/runner.py", "/work"]

    def run(self, work: Path, time_limit: int) -> subprocess.CompletedProcess:
        name = f"pflab-wk-{uuid.uuid4().hex[:12]}"
        out = Path(tempfile.mkdtemp(prefix="pflab_out_"))
        try:
            try:
                p = self._run(self.command(work, name, out), capture_output=True, timeout=time_limit + 20)
            except subprocess.TimeoutExpired:
                self.kill(name)
                raise
            f = out / "out.json"
            if os.path.lexists(f):                                 # the only thing that comes back: bounded, regular, a JSON object
                (work / "out.json").write_text(json.dumps(read_result(f)), encoding="utf-8")
            return p
        finally:
            shutil.rmtree(out, ignore_errors=True)

    def kill(self, name: str) -> None:
        try:                                                       # the client is gone; the container may not be
            self._run(["docker", "kill", name], capture_output=True, timeout=15)
        except Exception:
            pass


# The script the probe runs INSIDE the container. It prints one JSON object of named checks (True = contained as required).
PROBE_CODE = r'''
import json, os, socket
r = {}
def attempt(label, fn):
    try:
        fn(); r[label] = False
    except Exception:
        r[label] = True
def net():
    s = socket.socket(); s.settimeout(2); s.connect(("1.1.1.1", 53))
def dns():
    socket.getaddrinfo("example.com", 80)
def write_root():
    open("/app/should_not_exist", "w").write("x")
def write_work():
    open("/work/should_not_exist", "w").write("x")
attempt("network_closed", net)
attempt("dns_closed", dns)
attempt("root_read_only", write_root)
attempt("work_read_only", write_work)
r["no_host_home"] = not any(os.path.exists(p) for p in ("/host", "/Users", "/mnt/c", "/home/user", "/root/.pflab"))
r["no_secret_env"] = not any(k.upper().startswith(("ANTHROPIC", "AWS_", "GOOGLE_", "KITE", "TELEGRAM", "PFLAB_")) for k in os.environ if k != "PFLAB_OUT")
r["not_root"] = os.getuid() != 0
print(json.dumps(r))
'''


def probe(runner: Callable = subprocess.run, image: str = IMAGE, work: Optional[Path] = None, timeout_s: int = 60) -> dict:
    """Run the containment checks inside a container. {"ok": bool, "checks": {name: bool}, "why": str}. A missing Docker or image is
    {"ok": False} with the reason; a check that did not run is False, never assumed."""
    ok, why = _docker_ready(runner, image)
    if not ok:
        return {"ok": False, "checks": {}, "why": why}
    d = Path(work) if work else Path(tempfile.mkdtemp(prefix="pflab_probe_"))
    name = f"pflab-probe-{uuid.uuid4().hex[:10]}"
    try:
        p = runner(_flags(name, d, None) + [image, "python", "-I", "-c", PROBE_CODE], capture_output=True, timeout=timeout_s)
        text = (p.stdout.decode("utf-8", "replace") if isinstance(p.stdout, bytes) else str(p.stdout or "")).strip().splitlines()
        checks = json.loads(text[-1]) if p.returncode == 0 and text else {}
    except subprocess.TimeoutExpired:
        checks = {}
    except Exception as e:
        return {"ok": False, "checks": {}, "why": f"probe could not run: {type(e).__name__}: {str(e)[:160]}"}
    finally:
        if work is None:
            shutil.rmtree(d, ignore_errors=True)
    if not checks:
        return {"ok": False, "checks": {}, "why": "the probe printed no result: containment is not proven"}
    # a run past its limit must be killed: a loop of 30 s with a 2 s limit, then the container must be gone
    checks["time_limit_kills"] = _time_limit_check(runner, image, d if work else None)
    bad = [k for k, v in checks.items() if v is not True]
    return {"ok": not bad, "checks": checks, "why": ("failed: " + ", ".join(bad)) if bad else "contained"}


def _time_limit_check(runner: Callable, image: str, work: Optional[Path]) -> bool:
    name = f"pflab-probe-t-{uuid.uuid4().hex[:8]}"
    d = work or Path(tempfile.mkdtemp(prefix="pflab_probe_"))
    try:
        t0 = time.monotonic()
        try:
            runner(_flags(name, d, None) + [image, "python", "-I", "-c", "import time; time.sleep(30)"], capture_output=True, timeout=2)
            return False                                           # it should not have finished by itself
        except subprocess.TimeoutExpired:
            try:
                runner(["docker", "kill", name], capture_output=True, timeout=15)
            except Exception:
                pass
            gone = runner(["docker", "ps", "-q", "--filter", f"name={name}"], capture_output=True, timeout=10)
            alive = bool((gone.stdout or b"").strip()) if hasattr(gone, "stdout") else False
            return (time.monotonic() - t0) < 25 and not alive
    except Exception:
        return False
    finally:
        if work is None:
            shutil.rmtree(d, ignore_errors=True)


def _docker_ready(runner: Callable, image: str):
    try:
        info = runner(["docker", "info"], capture_output=True, timeout=PROBE_S)
    except FileNotFoundError:
        return False, "Docker is not installed"
    except Exception as e:
        return False, f"Docker did not answer ({type(e).__name__})"
    if info.returncode != 0:
        return False, "Docker Desktop is not running"
    try:
        img = runner(["docker", "image", "inspect", image], capture_output=True, timeout=PROBE_S)
    except Exception as e:
        return False, f"Docker did not answer ({type(e).__name__})"
    if img.returncode != 0:
        return False, f"the sandbox image {image} is not built (docker build -t {image} -f sandbox/Dockerfile .)"
    return True, ""


def status(runner: Callable = subprocess.run, now: Optional[float] = None, force: bool = False) -> dict:
    """{"ok": bool, "why": str}: Docker answers and the image exists; remembered for CACHE_S seconds."""
    t = time.time() if now is None else now
    if not force and _cache["at"] and t - _cache["at"] < CACHE_S:
        return {"ok": bool(_cache["ok"]), "why": _cache["why"]}
    ok, why = _docker_ready(runner, IMAGE)
    _cache.update({"at": t, "ok": ok, "why": why})
    return {"ok": ok, "why": why}


def available(runner: Callable = subprocess.run, now: Optional[float] = None, force: bool = False) -> bool:
    return status(runner, now, force)["ok"]


def blocked_by_probe(con) -> Optional[str]:
    """Why generated code must not run: the latest containment probe failed. None when it passed, or has not run yet (the first use is
    allowed to find out). Not read under PFLAB_SANDBOX=local, which is the workshop's explicit uncontained setting."""
    if os.environ.get("PFLAB_SANDBOX", "").lower() == "local":
        return None
    try:
        r = con.execute("SELECT ok, detail, checked_at FROM health_checks WHERE connector='sandbox' ORDER BY check_id DESC LIMIT 1").fetchone()
    except Exception:
        return None
    if r is not None and not r[0]:
        return f"the sandbox's containment probe failed on {str(r[2])[:16]} ({str(r[1])[:100]})"
    return None


def installed_app() -> bool:
    """True in an installed app (a release.toml): the uncontained path is refused there whatever the environment says."""
    try:
        from pflab import release
        return release.load() is not None
    except Exception:
        return False


def pick(python: str = sys.executable):
    """Docker when it works. Otherwise `SandboxUnavailable`: there is no fallback to the host. `PFLAB_SANDBOX=local` (the test suite, the
    developer's workshop) names the subprocess explicitly and is refused in an installed app; =docker insists on Docker."""
    want = os.environ.get("PFLAB_SANDBOX", "").lower()
    if want == "local":
        if installed_app():
            raise SandboxUnavailable("the uncontained subprocess is refused in the installed app; start Docker Desktop")
        return Local(python)
    s = {"ok": True, "why": ""} if want == "docker" else status()
    if not s["ok"]:
        raise SandboxUnavailable(s["why"] or "the sandbox is not available")
    return Docker()
