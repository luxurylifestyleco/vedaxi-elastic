#!/usr/bin/env bash
# ============================================================================
# Elastic Web — db-init.sh
# One-command database bootstrap:
#   1. Creates the 'elastic_web' database if it does not exist.
#   2. Applies all migrations in db/migrations/ (in filename order).
#   3. Loads db/seed.sql.
#
# Idempotent: safe to run repeatedly.
#
# Usage:  ./scripts/db-init.sh
# Env:    PGHOST, PGPORT, PGUSER, PGPASSWORD (optional, sane defaults below).
# ============================================================================
set -euo pipefail

# Resolve repo root (parent of scripts/).
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# psql.exe is a native Windows binary and cannot read MSYS paths like
# /c/Users/... Convert to a Windows-style path (C:/Users/...) for -f args.
if command -v cygpath >/dev/null 2>&1; then
    REPO_ROOT_WIN="$(cygpath -m "${REPO_ROOT}")"
else
    REPO_ROOT_WIN="${REPO_ROOT}"
fi

PSQL="${PSQL:-/c/Program Files/PostgreSQL/16/bin/psql.exe}"
PGHOST="${PGHOST:-localhost}"
PGPORT="${PGPORT:-5432}"
PGUSER="${PGUSER:-postgres}"
PGPASSWORD="${PGPASSWORD:-postgres}"
PGDATABASE="${PGDATABASE:-elastic_web}"

export PGPASSWORD

MIGRATIONS_DIR="${REPO_ROOT_WIN}/db/migrations"
SEED_FILE="${REPO_ROOT_WIN}/db/seed.sql"

echo "=============================================="
echo " Elastic Web — Database Init"
echo "=============================================="
echo "Host     : ${PGHOST}:${PGPORT}"
echo "Database : ${PGDATABASE}"
echo "User     : ${PGUSER}"
echo "Migrations: ${MIGRATIONS_DIR}"
echo "Seed      : ${SEED_FILE}"
echo ""

# 1. Create database if missing (connect to 'postgres' maintenance DB).
DB_EXISTS=$("$PSQL" -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d postgres -tAc \
    "SELECT 1 FROM pg_database WHERE datname='${PGDATABASE}';" 2>&1)
if [ "$DB_EXISTS" = "1" ]; then
    echo "[OK]   Database '${PGDATABASE}' already exists."
else
    echo "[..]   Creating database '${PGDATABASE}'..."
    "$PSQL" -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d postgres -c \
        "CREATE DATABASE \"${PGDATABASE}\";" >/dev/null
    echo "[OK]   Database '${PGDATABASE}' created."
fi

# 2. Apply migrations in order.
echo ""
echo "Applying migrations:"
for f in "$MIGRATIONS_DIR"/*.sql; do
    [ -e "$f" ] || { echo "[WARN] No migrations found in ${MIGRATIONS_DIR}"; break; }
    echo "  [..]   $(basename "$f")"
    "$PSQL" -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d "$PGDATABASE" -v ON_ERROR_STOP=1 -f "$f" >/dev/null
    echo "  [OK]   $(basename "$f") applied."
done

# 3. Load seed.
echo ""
if [ -f "$SEED_FILE" ]; then
    echo "[..]   Loading seed data..."
    "$PSQL" -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d "$PGDATABASE" -v ON_ERROR_STOP=1 -f "$SEED_FILE" >/dev/null
    echo "[OK]   Seed data loaded."
else
    echo "[WARN] Seed file not found: ${SEED_FILE}"
fi

echo ""
echo "=============================================="
echo " Init complete. Run ./scripts/db-health.sh to verify."
echo "=============================================="
