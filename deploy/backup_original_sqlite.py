"""Create and verify a consistent SQLite backup, without changing the source."""
import argparse
import json
from pathlib import Path
import sqlite3

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("source", type=Path)
parser.add_argument("destination", type=Path)
args = parser.parse_args()
source = args.source.resolve(strict=True)
destination = args.destination.resolve()
if destination.exists() or source == destination:
    raise SystemExit("Refusing to overwrite an existing database or backup.")
destination.parent.mkdir(parents=True, exist_ok=True)
source_db = sqlite3.connect(source.as_uri() + "?mode=ro", uri=True, timeout=60)
source_db.execute("PRAGMA query_only=ON")
source_count = source_db.execute("SELECT COUNT(*) FROM core_knowledgeentity").fetchone()[0]
last_progress = -1


def progress(status, remaining, total):
    global last_progress
    percent = int(100 * (total - remaining) / max(total, 1))
    if percent // 10 > last_progress:
        last_progress = percent // 10
        print(f"Backup: {percent}%", flush=True)


try:
    with sqlite3.connect(destination, timeout=60) as backup_db:
        source_db.backup(backup_db, pages=8192, progress=progress)
        integrity = backup_db.execute("PRAGMA quick_check").fetchone()[0]
        backup_count = backup_db.execute("SELECT COUNT(*) FROM core_knowledgeentity").fetchone()[0]
        if integrity != "ok" or backup_count != source_count:
            raise RuntimeError("Backup verification failed; source remains unchanged.")
    print(json.dumps({"backup": str(destination), "bytes": destination.stat().st_size,
                      "knowledge_entities": backup_count, "quick_check": integrity}), flush=True)
finally:
    source_db.close()
