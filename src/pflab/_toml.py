try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore


def load(path):
    with open(path, "rb") as f:
        return tomllib.load(f)
