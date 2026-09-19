FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000

WORKDIR /app

COPY pyproject.toml README.md ./
COPY acg ./acg
COPY web ./web

# Installed editable on purpose: it keeps one source tree, so importlib.metadata
# can read the version while acg/ and web/ stay resolvable from the same root.
RUN pip install --no-cache-dir -e .

# The runtime has no reason to own its own source.
RUN useradd --create-home --uid 1000 appuser \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# The hosted deployment runs on Vercel, which does not use this file. The image
# exists for local reproduction and for any container host, which typically
# injects its own $PORT.
CMD ["sh", "-c", "uvicorn acg.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
