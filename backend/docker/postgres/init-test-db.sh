#!/bin/bash
set -euo pipefail

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<'SQL'
SELECT 'CREATE DATABASE ai_shorts_engine_test'
WHERE NOT EXISTS (
    SELECT FROM pg_database WHERE datname = 'ai_shorts_engine_test'
)\gexec
SQL
