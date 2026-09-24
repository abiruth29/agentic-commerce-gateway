"""The container image must ship every directory the app reads at runtime.

This failed once already, silently. The console added a runtime read of
`corpus/`, the Dockerfile kept copying only `acg/` and `web/`, and nothing
noticed: the image still built, still booted and still answered `/health`. It
would have failed on the first real request.

So the check runs from the other direction. It finds every directory the
package resolves relative to the repository root — the same way the code
does, by scanning for paths built from `__file__` — and asserts the
Dockerfile copies each one. A new runtime read that the image does not ship
fails here rather than in a deployed container.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCKERFILE = (ROOT / "Dockerfile").read_text(encoding="utf-8")


def copied_paths() -> set[str]:
    """Every source path named in a COPY instruction."""
    paths: set[str] = set()
    for line in DOCKERFILE.splitlines():
        match = re.match(r"\s*COPY\s+(.+)\s+\S+\s*$", line)
        if match:
            paths.update(match.group(1).split())
    return paths


def runtime_directories() -> set[str]:
    """Top-level repo directories the package reads relative to __file__.

    Matches the idiom the code uses: a path climbed out of the package with
    `.parent` and then joined with a quoted directory name.
    """
    found: set[str] = set()
    pattern = re.compile(r'Path\(__file__\)[^\n]*?\.parent\s*/\s*"([a-z_]+)"')
    for source in (ROOT / "acg").rglob("*.py"):
        found.update(pattern.findall(source.read_text(encoding="utf-8")))
    return found


def test_the_scan_finds_the_known_runtime_directories() -> None:
    # Guards the guard: a scan that found nothing would pass vacuously.
    assert {"web", "corpus"} <= runtime_directories()


def test_every_runtime_directory_is_copied_into_the_image() -> None:
    missing = runtime_directories() - copied_paths()
    assert not missing, f"the image does not ship {sorted(missing)}"


def test_the_package_itself_is_copied() -> None:
    assert "acg" in copied_paths()
