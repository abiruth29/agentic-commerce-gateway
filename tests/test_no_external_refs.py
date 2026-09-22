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

XML_NAMESPACES = frozenset(
    {
        "http://www.w3.org/2000/svg",
        "http://www.w3.org/1999/xlink",
    }
)
"""URIs that are identifiers rather than addresses.

An `xmlns` value is never fetched — it names a vocabulary, and the string is
fixed by the specification. Excluding exactly these two, by full match rather
than by prefix, keeps an inline SVG legal without weakening the guard: any
other w3.org URL, and any URL that merely contains one of these as a prefix,
still fails.
"""


def _external_refs(text: str) -> list[str]:
    return [ref for ref in EXTERNAL_REF.findall(text) if ref not in XML_NAMESPACES]


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

    found = _external_refs(response.text)
    assert not found, f"{path} references external hosts: {found}"


def test_the_namespace_exclusion_is_narrow() -> None:
    # Guards the exemption. It must cover the two fixed namespace strings and
    # nothing that merely looks like them.
    assert _external_refs('xmlns="http://www.w3.org/2000/svg"') == []
    assert _external_refs('src="http://www.w3.org/2000/svg/evil.js"')
    assert _external_refs('src="http://www.w3.org/"')
    assert _external_refs('src="https://cdn.example.com/x.js"')


@pytest.mark.parametrize("path", ["/docs", "/redoc"])
def test_cdn_backed_api_docs_stay_disabled(client: TestClient, path: str) -> None:
    assert client.get(path).status_code == 404
