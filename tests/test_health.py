import tomllib
from pathlib import Path

from fastapi.testclient import TestClient

PYPROJECT = Path(__file__).resolve().parent.parent / "pyproject.toml"


def _pyproject_version() -> str:
    with PYPROJECT.open("rb") as handle:
        return tomllib.load(handle)["project"]["version"]


def test_health_reports_ok_and_the_pyproject_version(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    # pyproject.toml is the single source of truth for the version; the probe
    # must report exactly that, not a second hand-maintained copy.
    assert response.json() == {"status": "ok", "version": _pyproject_version()}


def test_console_is_served_at_root(client: TestClient) -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")


def test_unknown_path_is_a_404_from_the_app(client: TestClient) -> None:
    response = client.get("/definitely-not-a-route")

    assert response.status_code == 404
