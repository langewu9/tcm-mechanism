#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ENV_FILE:-$ROOT_DIR/.env.production}"
BACKUP_DIR="${1:-$ROOT_DIR/backups}"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "Production environment file not found: $ENV_FILE" >&2
  exit 1
fi

mkdir -p "$BACKUP_DIR"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
OUTPUT="$BACKUP_DIR/tcm-platform-$STAMP.dump"
TEMP_OUTPUT="$OUTPUT.partial"
COMPOSE=(docker compose --env-file "$ENV_FILE" -f "$ROOT_DIR/deploy/compose.production.yml")
trap 'rm -f "$TEMP_OUTPUT"' EXIT

"${COMPOSE[@]}" exec -T postgres sh -c \
  'PGPASSWORD="$POSTGRES_PASSWORD" pg_dump -h 127.0.0.1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' \
  > "$TEMP_OUTPUT"
mv "$TEMP_OUTPUT" "$OUTPUT"
(cd "$BACKUP_DIR" && sha256sum "$(basename "$OUTPUT")" > "$(basename "$OUTPUT").sha256")
trap - EXIT
echo "Database backup created: $OUTPUT"
echo "Checksum file created: $OUTPUT.sha256"
