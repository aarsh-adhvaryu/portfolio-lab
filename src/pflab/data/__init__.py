import os
from pathlib import Path


def data_dir() -> Path:
    return Path(os.environ.get("PFLAB_DATA_DIR", "data")).expanduser()
