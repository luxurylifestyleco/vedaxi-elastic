#!/usr/bin/env bash
# ============================================================================
# Elastic Web — db-health.sh
# Connects to the elastic_web database and reports status: connectivity,
# server version, pgvector availability, and table presence/counts.
#
# Usage:  ./scripts/db-health.sh
# Env:    PGHOST, PGPORT, PGUSER, PGPASSWORD, PGDATABASE (all optional, sane
#         defaults below).
# ============================================================================
set -euo pipefail

PSQL="${PSQL:-/c/Program Files/PostgreSQL/16/bin/psql.exe}"
PGHOST="${PGHOST:-localhost}"
PGPORT="${PGPORT:-5432}"
PGUSER="${PGUSER:-postgres}"
PGPASSWORD="${PGPASSWORD:-postgres}"
PGDATABASE="${PGDATABASE:-elastic_web}"

export PGPASSWORD

echo "=============================================="
echo " Elastic Web — Database Health Check"
echo "=============================================="
echo "Host     : ${PGHOST}:${PGPORT}"
echo "Database : ${PGDATABASE}"
echo "User     : ${PGUSER}"
echo ""

# 1. Connectivity + server version
if ! SERVER_VERSION=$("$PSQL" -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d "$PGDATABASE" -tAc "SELECT version();" 2>&1); then
    echo "[FAIL] Cannot connect to database '${PGDATABASE}'."
    echo "       ${SERVER_VERSION}"
    echo "       Hint: run ./scripts/db-init.sh first to create it."
    exit 1
fi
echo "[OK]   Connected. Server: ${SERVER_VERSION}"

# 2. pgvector availability
VECTOR_AVAIL=$("$PSQL" -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d "$PGDATABASE" -tAc \
    "SELECT count(*) FROM pg_available_extensions WHERE name='vector';" 2>/dev/null || echo "0")
if [ "$VECTOR_AVAIL" = "1" ]; then
    VECTOR_INSTALLED=$("$PSQL" -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d "$PGDATABASE" -tAc \
        "SELECT count(*) FROM pg_extension WHERE extname='vector';" 2>/dev/null || echo "0")
    if [ "$VECTOR_INSTALLED" = "1" ]; then
        echo "[OK]   pgvector: available AND installed."
    else
        echo "[WARN] pgvector: available but not installed in this database."
    fi
else
    echo "[WARN] pgvector: NOT available on this server. Embeddings fall back to JSONB arrays."
fi

# 3. Required tables
echo ""
echo "Tables:"
REQUIRED_TABLES=(capabilities intent_examples recipes recipe_versions \
                 execution_traces execution_steps evaluations benchmark_runs)
MISSING=0
for t in "${REQUIRED_TABLES[@]}"; do
    COUNT=$("$PSQL" -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d "$PGDATABASE" -tAc \
        "SELECT count(*) FROM information_schema.tables WHERE table_schema='public' AND table_name='${t}';" 2>/dev/null || echo "0")
    if [ "$COUNT" = "1" ]; then
        ROWS=$("$PSQL" -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d "$PGDATABASE" -tAc \
            "SELECT count(*) FROM \"${t}\";" 2>/dev/null || echo "?")
        printf "  [OK]   %-20s (%s rows)\n" "$t" "$ROWS"
    else
        printf "  [FAIL] %-20s (missing)\n" "$t"
        MISSING=1
    fi
done

echo ""
if [ "$MISSING" = "1" ]; then
    echo "RESULT: DEGRADED — one or more required tables are missing."
    echo "        Run ./scripts/db-init.sh to apply migrations and seed."
    exit 1
else
    echo "RESULT: HEALTHY — all 8 required tables present."
    exit 0
fi
