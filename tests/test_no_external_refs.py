"""The project makes no external asset or network references in anything it serves.

This is enforced by discovery rather than by a list: every parameterless GET
route the app registers and every file under web/ is fetched and scanned. A
route or page added later is covered without anyone remembering to add it,
which is exactly how FastAPI's CDN-backed /docs page once slipped through.
"""

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from starlette.routing import Route

from acg.main import WEB_DIR, app

# An absolute URL, or a protocol-relative one inside a src/href attribute or a
# CSS url(). Bare "//" is not matched on its own because it is also the syntax
# of a JavaScript comment.
EXTERNAL_REF = re.compile(
    r"""https?://[^\s"'<>()]+"""
    r"""|(?:src|href)\s*=\s*["']//"""
    r"""|url\(\s*["']?//"""
)


def _served_paths() -> list[str]:
    paths: list[str] = []

    for route in app.routes:
        # Route covers both API endpoints and FastAPI's own schema route; the
        # static Mount is not a Route and is covered file by file below.
        if not isinstance(route, Route):
            continue
        if "GET" not in (route.methods or set()) or "{" in route.path:
            continue
        paths.append(route.path)

    for file in sorted(Path(WEB_DIR).rglob("*")):
        if file.is_file():
            paths.append("/" + file.relative_to(WEB_DIR).as_posix())

    return paths


SERVED_PATHS = _served_paths()


def test_discovery_found_the_known_surface() -> None:
    # Guards the guard: if discovery silently returned nothing, every
    # parametrised case below would vanish and the suite would pass vacuously.
    assert "/health" in SERVED_PATHS
    assert "/openapi.json" in SERVED_PATHS
    assert "/index.html" in SERVED_PATHS


@pytest.mark.parametrize("path", SERVED_PATHS)
def test_served_content_has_no_external_references(
    client: TestClient, path: str
) -> None:
    response = client.get(path)
    assert response.status_code == 200, f"{path} is not servable"

    found = EXTERNAL_REF.findall(response.text)
    assert not found, f"{path} references external hosts: {found}"


@pytest.mark.parametrize("path", ["/docs", "/redoc"])
def test_cdn_backed_api_docs_stay_disabled(client: TestClient, path: str) -> None:
    assert client.get(path).status_code == 404
