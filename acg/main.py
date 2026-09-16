"""FastAPI application entrypoint.

Stage 0 is a walking skeleton. There is deliberately no domain logic here: the
only claim this module makes is that the deployment pipeline works end to end.
Everything real arrives in later stages.
"""

from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from acg import __version__

# Local development reads .env; in deployment these come from host secrets and
# there is no file to find, which load_dotenv treats as a no-op.
load_dotenv()

WEB_DIR = Path(__file__).resolve().parent.parent / "web"

app = FastAPI(
    title="Agentic Commerce Gateway",
    description="A trust gateway for agent-initiated payments.",
    version=__version__,
)


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness probe.

    Deliberately dependency-free. It must answer 200 even when every downstream
    integration is absent or misconfigured, because its job is to tell you the
    process is up — not to tell you the system is healthy.
    """
    return {"status": "ok", "version": __version__}


# Mounted last and at the root so it only catches paths no API route claimed;
# routes registered above win. html=True makes "/" serve web/index.html.
app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
