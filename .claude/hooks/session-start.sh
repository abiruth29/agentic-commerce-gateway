#!/bin/bash
# Prepares a Claude Code on the web container so tests, linters and the app can
# run without a manual setup step. Local checkouts are left alone: the README's
# venv flow is the right thing there, and this script would otherwise install
# into whatever interpreter happens to be active.
set -euo pipefail

if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

cd "${CLAUDE_PROJECT_DIR:-$(dirname "$0")/../..}"

# Editable install so the package resolves from the checkout, with the dev
# extra CI uses (pytest, httpx for TestClient, ruff). Re-running is cheap: pip
# is a no-op once the pinned versions are already present.
#
# The container has no virtualenv and runs as root, which pip warns about on
# every run. Silenced because a hook's output becomes session context, and this
# warning describes the container, not anything wrong with the project.
PIP_ROOT_USER_ACTION=ignore pip install --quiet --disable-pip-version-check -e ".[dev]"

# The container ships general-purpose tooling (its own ruff and pytest) on PATH
# ahead of where pip puts this project's console scripts. Left alone, `ruff`
# resolves to a different version than pyproject.toml pins, and `pytest`
# resolves to an isolated install that cannot import fastapi — so the suite
# fails at conftest with a misleading ModuleNotFoundError. Putting the
# interpreter's own script directory first makes the bare commands agree with
# `python -m`, and with what CI runs.
SCRIPTS_DIR="$(python -c 'import sysconfig; print(sysconfig.get_path("scripts"))')"
if [ -n "${CLAUDE_ENV_FILE:-}" ] && [ -n "$SCRIPTS_DIR" ]; then
  echo "export PATH=\"$SCRIPTS_DIR:\$PATH\"" >> "$CLAUDE_ENV_FILE"
fi

# acg.main calls load_dotenv() at import. A missing file is a no-op, so this is
# a convenience only: it seeds the defaults from .env.example, which ship with
# MOCK_MODE=true and no credentials. An existing .env is never overwritten.
if [ ! -f .env ] && [ -f .env.example ]; then
  cp .env.example .env
fi
