"""What HQ needs from the dashboard's runtime, for when the window is closed and the scheduled tick runs HQ as a job.

The agents take one object `rt` with the runtime's names (cursor, clock, bump, pm_dir, data_root, repo, secrets,
settings), so the same code runs inside the dashboard (the real `app.runtime.Runtime`) and in the tick (this `Desk`).
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional


class Desk:
    def __init__(self, con, pm_dir: Path, data_root: Path, repo: Path, secrets=None, settings: Optional[dict] = None,
                 clock: Callable[[], datetime] = datetime.now):
        from pflab.app import settings as st
        self.con, self.pm_dir, self.data_root, self.repo = con, Path(pm_dir), Path(data_root), Path(repo)
        self.secrets, self.clock = secrets, clock
        self.settings = settings if settings is not None else st.load(self.pm_dir)
        self.sims_running = False
        self.sims_error: Optional[str] = None
        self.attended = False                      # nobody at the screen: inbox work finishes before the tick ends
        # S67: what the shared tools read from the dashboard's runtime, so `system_status` and the rest answer the same here
        self.busy: Optional[str] = None
        self.wanted: list = []
        self.update_ready = False
        self.live_indices: dict = {}
        self.catching_up: Optional[str] = None

    def cursor(self):
        return self.con.cursor()                         # S69: worker threads each take their own (the store is shared, the connection object is not)

    def mc_path(self) -> Path:
        return self.pm_dir / "app" / "cache" / "montecarlo.json"

    def mc_cache(self) -> Optional[dict]:
        import json
        p = self.mc_path()
        try:
            return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None
        except ValueError:
            return None

    def bump(self, *topics: str) -> None:
        pass

    def request_run(self, name: str) -> Any:
        from pflab.service import jobs, tasks  # noqa: F401
        return jobs.run_job(jobs.Ctx(self.con, self.clock(), self.pm_dir, self.data_root, self.repo, secrets=self.secrets),
                            jobs.REGISTRY[name])


def from_ctx(ctx) -> Desk:
    return Desk(ctx.con, ctx.pm_dir, ctx.data_root, ctx.repo, ctx.secrets, clock=lambda: ctx.now)
