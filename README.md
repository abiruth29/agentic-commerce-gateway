# Agentic Commerce Gateway

A trust gateway for agent-initiated payments — it sits between an AI buyer agent's purchase request and the money, and decides whether that request is honest.

## Run locally

Requires Python 3.11 or newer.

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e .
cp .env.example .env             # Windows: copy .env.example .env
uvicorn acg.main:app --reload
```

Then:

- <http://127.0.0.1:8000/> — console
- <http://127.0.0.1:8000/health> — liveness probe

```bash
curl -s http://127.0.0.1:8000/health
# {"status":"ok","version":"0.1.0"}
```
