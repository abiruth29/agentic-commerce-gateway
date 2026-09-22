"""Guard against a package that exists on disk but never reaches a build.

This failure mode is invisible in normal development. CI and local work both
use `pip install -e .`, which puts the source tree on `sys.path`, so every
module imports fine no matter what the build is configured to ship. The first
symptom is an ImportError in a deployed build, long after the mistake.

So the check compares the packages setuptools would collect against the ones
actually on disk, rather than importing anything.
"""

import tomllib
from pathlib import Path

from setuptools import find_packages

ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = ROOT / "pyproject.toml"


def _packages_on_disk() -> set[str]:
    """Every directory under acg/ that is a package, in dotted form."""
    found = set()
    for init in ROOT.joinpath("acg").rglob("__init__.py"):
        found.add(".".join(init.parent.relative_to(ROOT).parts))
    return found


def _configured_include() -> list[str]:
    with PYPROJECT.open("rb") as handle:
        config = tomllib.load(handle)
    return config["tool"]["setuptools"]["packages"]["find"]["include"]


def test_the_build_collects_every_package_on_disk() -> None:
    """A subpackage that exists but is not collected is shipped broken."""
    collected = set(find_packages(where=str(ROOT), include=_configured_include()))

    missing = _packages_on_disk() - collected
    assert not missing, (
        f"these packages exist on disk but would be left out of a build: "
        f"{sorted(missing)}"
    )


def test_discovery_is_used_rather_than_an_explicit_list() -> None:
    """An explicit list is the thing that silently goes stale.

    Reintroducing `packages = [...]` would pass the test above on the day it
    was written and quietly omit the next subpackage added.
    """
    with PYPROJECT.open("rb") as handle:
        setuptools_config = tomllib.load(handle)["tool"]["setuptools"]

    assert "packages" in setuptools_config
    assert "find" in setuptools_config["packages"], (
        "package discovery must stay automatic; an explicit list omits new "
        "subpackages without failing anything until deployment"
    )


def test_the_deployed_entrypoint_is_inside_a_collected_package() -> None:
    """The Vercel entrypoint must be in something the build actually ships."""
    with PYPROJECT.open("rb") as handle:
        entrypoint = tomllib.load(handle)["tool"]["vercel"]["entrypoint"]

    module = entrypoint.split(":")[0]
    package = module.rsplit(".", 1)[0]

    assert package in set(find_packages(where=str(ROOT), include=_configured_include()))
