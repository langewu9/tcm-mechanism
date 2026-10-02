#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ENV_FILE:-$ROOT_DIR/.env.production}"

usage() {
  echo "Usage: $0 --confirm /absolute/path/to/tcm-platform-TIMESTAMP.dump" >&2
  echo "This replaces the current production database. A checksum file (.sha256) is required." >&2
}

if [[ "${1:-}" != "--confirm" || -z "${2:-}" || $# -ne 2 ]]; then
  usage
  exit 2
fi
if [[ ! -f "$ENV_FILE" || ! -f "$2" || ! -f "$2.sha256" ]]; then
  echo "Environment, backup, or backup checksum file is missing." >&2
  exit 1
fi

BACKUP="$(realpath "$2")"
(cd "$(dirname "$BACKUP")" && sha256sum --check "$(basename "$BACKUP").sha256")
echo "This will overwrite all current platform database records. Stop users and verify the backup first."
read -r -p 'Type RESTORE to continue: ' ANSWER
if [[ "$ANSWER" != "RESTORE" ]]; then
  echo "Restore cancelled."
  exit 1
fi

COMPOSE=(docker compose --env-file "$ENV_FILE" -f "$ROOT_DIR/deploy/compose.production.yml")
"${COMPOSE[@]}" stop nginx api worker
"${COMPOSE[@]}" exec -T postgres sh -c \
  'PGPASSWORD="$POSTGRES_PASSWORD" pg_restore --clean --if-exists --no-owner --exit-on-error -h 127.0.0.1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -' \
  < "$BACKUP"
echo "Database restore finished. Review PostgreSQL logs, then start services with docker compose up -d."
