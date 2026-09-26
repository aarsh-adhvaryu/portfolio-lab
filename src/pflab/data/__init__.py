import os
from pathlib import Path


def data_dir() -> Path:
    """Where raw and derived data live. `PFLAB_DATA_DIR`, else `./data`.

    Never rely on the fallback: it is relative, so a command launched from
    anywhere but the repo root resolves to a different (usually empty)
    directory instead of failing. CLAUDE.md "Repo layout" says where it is
    set and how to verify it.
    """
    return Path(os.environ.get("PFLAB_DATA_DIR", "data")).expanduser()


def experiments_dir() -> Path:
    r"""Where sweeps and runs are written. `PFLAB_EXPERIMENTS_DIR`, else
    `./experiments`.

    Same rule and the same reason as `data_dir`: **never rely on the
    fallback.** It matters more here than it looks. From 2026-09-26 a locked
    experiment runs from a detached worktree at `D:\pl_runs\<ID>`, so the
    working directory is NOT the repo — and a relative `experiments` would
    scatter results into each worktree, where the next `git worktree prune`
    would delete them. Every sweep writes to the one real
    `D:\portfolio_lab\experiments` whatever directory it was launched from.
    """
    return Path(os.environ.get("PFLAB_EXPERIMENTS_DIR", "experiments")).expanduser()
