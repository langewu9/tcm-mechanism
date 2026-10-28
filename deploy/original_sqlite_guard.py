"""Fail closed if the original mounted SQLite database is missing or empty."""
import json
from pathlib import Path
import sqlite3

database = Path("/app/var/qa.sqlite3")
if not database.is_file():
    raise SystemExit("Original database is not mounted. Refusing to create a new database.")
with sqlite3.connect(database.as_uri() + "?mode=ro", uri=True, timeout=60) as db:
    db.execute("PRAGMA query_only=ON")
    entities = db.execute("SELECT COUNT(*) FROM core_knowledgeentity").fetchone()[0]
    users = db.execute("SELECT COUNT(*) FROM auth_user").fetchone()[0]
    if entities == 0 or users == 0:
        raise SystemExit("Expected original populated database; refusing empty replacement.")
    print(json.dumps({"database": str(database), "knowledge_entities": entities,
                      "users": users, "mode": "existing-original-database"}), flush=True)
