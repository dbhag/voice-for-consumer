#!/usr/bin/env bash
# Idempotently ensure the local Postgres role/db/schema that DATABASE_URL
# points at exist. Run by `make db-setup` and by dev.sh's startup, so a
# fresh machine (or a repo that moved paths/machines) doesn't need a manual
# `createuser`/`createdb` step before the stack comes up.
#
# Only touches a *local* Postgres (localhost/127.0.0.1) — if DATABASE_URL
# points elsewhere (a managed/remote Postgres), this is a no-op, since
# provisioning a remote instance isn't this script's job.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [ -f .venv/bin/activate ]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi

if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

DATABASE_URL="${DATABASE_URL:-postgresql+asyncpg://proxy:proxy@localhost:5432/proxy}"

read -r DB_HOST DB_ROLE DB_PASSWORD DB_NAME <<<"$(python3 - "$DATABASE_URL" <<'PYEOF'
import sys
from urllib.parse import urlsplit

u = urlsplit(sys.argv[1].replace("postgresql+asyncpg://", "postgresql://"))
print(u.hostname or "", u.username or "", u.password or "", (u.path or "/").lstrip("/"))
PYEOF
)"

if [[ "$DB_HOST" != "localhost" && "$DB_HOST" != "127.0.0.1" ]]; then
  echo "[db-setup] DATABASE_URL host is '$DB_HOST', not local; skipping role/db bootstrap." >&2
  exit 0
fi

if ! psql -X -tAc "SELECT 1 FROM pg_roles WHERE rolname='${DB_ROLE}'" postgres 2>/dev/null | grep -q 1; then
  echo "[db-setup] creating postgres role '${DB_ROLE}'..." >&2
  createuser -s "${DB_ROLE}"
fi
psql -X -tAc "ALTER ROLE ${DB_ROLE} WITH PASSWORD '${DB_PASSWORD}'" postgres >/dev/null

if ! psql -X -tAc "SELECT 1 FROM pg_database WHERE datname='${DB_NAME}'" postgres 2>/dev/null | grep -q 1; then
  echo "[db-setup] creating postgres database '${DB_NAME}' (owner ${DB_ROLE})..." >&2
  createdb -O "${DB_ROLE}" "${DB_NAME}"
fi

echo "[db-setup] role '${DB_ROLE}' and database '${DB_NAME}' exist; ensuring schema..." >&2
PYTHONPATH="$ROOT_DIR" python3 "$ROOT_DIR/scripts/init_schema.py"
