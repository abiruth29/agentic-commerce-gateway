"""Agentic Commerce Gateway.

A trust gateway for agent-initiated payments.
"""

import tomllib
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _installed_version
from pathlib import Path


def _read_version() -> str:
    """Resolve the version from the single source of truth in pyproject.toml.

    The installed distribution metadata is the normal path. The fallback exists
    so the app still starts when run straight from a checkout that has not been
    pip-installed, which is how it is usually run during development.
    """
    try:
        return _installed_version("acg")
    except PackageNotFoundError:
        pass

    pyproject = Path(__file__).resolve().parent.parent / "pyproject.toml"
    try:
        with pyproject.open("rb") as handle:
            return str(tomllib.load(handle)["project"]["version"])
    except (OSError, KeyError):
        return "0.0.0+unknown"


__version__ = _read_version()

__all__ = ["__version__"]
