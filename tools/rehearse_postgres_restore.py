"""Back up local acceptance data and restore it into a new, separate database.

Never drops databases, overwrites a backup, or targets the original preview.
Includes private media and source SQLite files; credentials stay outside Git.
This is a local rehearsal, not a production backup scheduler.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import psycopg
from psycopg import sql

from postgres_acceptance import APP, PG_BIN, VAR, environment


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def file_manifest(root):
    files = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise RuntimeError("Refusing symlinks in acceptance storage.")
        if path.is_file():
            files[str(path.relative_to(root))] = {"bytes": path.stat().st_size, "sha256": sha256(path)}
    return files


def connect(profile, database):
    return psycopg.connect(host=profile["host"], port=profile["port"], user=profile["user"],
                           password=profile["password"], dbname=database, autocommit=True)


def database_fingerprint(connection):
    """Hash all public rows, including owners, provenance, audits and sessions."""
    tables = {}
    names = connection.execute("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename").fetchall()
    for (name,) in names:
        rows = connection.execute(sql.SQL("SELECT * FROM public.{}").format(sql.Identifier(name))).fetchall()
        serialized = sorted(json.dumps(row, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":")) for row in rows)
        tables[name] = {"rows": len(rows), "sha256": hashlib.sha256("\n".join(serialized).encode()).hexdigest()}
    sequences = {}
    names = connection.execute("SELECT sequencename FROM pg_sequences WHERE schemaname='public' ORDER BY sequencename").fetchall()
    for (name,) in names:
        sequences[name] = list(connection.execute(sql.SQL("SELECT last_value, is_called FROM public.{}").format(sql.Identifier(name))).fetchone())
    return {"tables": tables, "sequences": sequences}


def verify_restored_api(directory):
    manifest = json.loads((directory / "manifest.json").read_text())
    database = manifest["restoredDatabase"]
    if not database.startswith("tcm_acceptance_restore_") or not database.replace("_", "").isalnum():
        raise RuntimeError("Unexpected restore target.")
    os.environ["DATABASE_URL"] = os.environ["DATABASE_URL"].rsplit("/", 1)[0] + "/" + database
    os.environ["MEDIA_ROOT"] = str(directory / "media")
    os.environ["SQLITE_SOURCE_ROOT"] = str(directory / "source-databases")
    sys.path.insert(0, str(APP))
    import django
    django.setup()
    from django.contrib.auth import get_user_model
    from django.core.files.storage import default_storage
    from rest_framework.test import APIClient
    from apps.core.models import AnalysisTask, ResearchDataset, VisualizationArtifact

    accounts = json.loads((VAR / "accounts.json").read_text())
    users = {key: get_user_model().objects.get(pk=value["id"]) for key, value in accounts.items()}
    clients = {}
    for key, user in users.items():
        client = APIClient(); client.force_authenticate(user=user); clients[key] = client
    verified_files = 0
    for record in [*ResearchDataset.objects.all(), *VisualizationArtifact.objects.all()]:
        assert sha256(Path(default_storage.path(record.storage_key))) == record.content_sha256
        verified_files += 1
    report = json.loads((VAR / "acceptance-result.json").read_text())
    dataset = ResearchDataset.objects.get(pk=report["datasetId"])
    assert dataset.owner_id == users["a"].pk
    dataset_url = f"/api/v1/research/datasets/{dataset.pk}/"
    owner_response = clients["a"].get(dataset_url + "download/")
    assert owner_response.status_code == 200
    assert hashlib.sha256(b"".join(owner_response.streaming_content)).hexdigest() == dataset.content_sha256
    assert clients["b"].get(dataset_url + "download/").status_code == 404
    assert clients["admin"].get(dataset_url).data["owner_id"] == users["a"].pk
    artifacts = VisualizationArtifact.objects.filter(task_id=report["graphTaskId"])
    for artifact in artifacts:
        url = f"/api/v1/research/analysis-artifacts/{artifact.pk}/download/"
        response = clients["a"].get(url)
        assert response.status_code == 200
        assert hashlib.sha256(b"".join(response.streaming_content)).hexdigest() == artifact.content_sha256
        assert clients["b"].get(url).status_code == 404
    task = AnalysisTask.objects.get(pk=report["graphTaskId"])
    assert task.result["counts"]["evidenceRecords"] == 200 and task.owner_id == users["a"].pk
    result = {"storedFilesVerified": verified_files, "downloadHashesMatch": True,
              "crossOwnerDenied": True, "adminPreservedOwner": True, "savedEvidenceRestored": True}
    (directory / "restored-api-result.json").write_text(json.dumps(result, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify-restore", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    profile = environment()
    if args.verify_restore:
        directory = args.verify_restore.resolve()
        if directory.parent != (VAR / "backups").resolve():
            raise RuntimeError("Refusing a restore outside the acceptance backup directory.")
        verify_restored_api(directory)
        return

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    directory = VAR / "backups" / stamp
    directory.mkdir(parents=True, mode=0o700, exist_ok=False)
    restored_database = "tcm_acceptance_restore_" + stamp
    with connect(profile, profile["database"]) as original:
        pending = original.execute("SELECT count(*) FROM core_analysistask WHERE status IN ('queued','pending','running')").fetchone()[0]
        pending += original.execute("SELECT count(*) FROM core_syncrun WHERE status IN ('pending','running')").fetchone()[0]
        if pending:
            raise RuntimeError("Wait for acceptance tasks to finish before the rehearsal.")
        before = database_fingerprint(original)
        media = file_manifest(VAR / "media")
        sources = file_manifest(VAR / "source-databases")
        subprocess_env = {**os.environ, "PGHOST": profile["host"], "PGPORT": str(profile["port"]),
                          "PGUSER": profile["user"], "PGPASSWORD": profile["password"], "PGDATABASE": profile["database"]}
        dump = directory / "database.dump"
        subprocess.run([str(PG_BIN / "pg_dump"), "--format=custom", "--compress=0", "--file", str(dump)],
                       env=subprocess_env, check=True)
        dump.chmod(0o600)
        shutil.copytree(VAR / "media", directory / "media")
        shutil.copytree(VAR / "source-databases", directory / "source-databases")
        assert media == file_manifest(directory / "media")
        assert sources == file_manifest(directory / "source-databases")
        assert before == database_fingerprint(original), "Acceptance data changed while backing up; do not claim success."
        original.execute(sql.SQL("CREATE DATABASE {} TEMPLATE template0").format(sql.Identifier(restored_database)))
        subprocess.run([str(PG_BIN / "pg_restore"), "--no-owner", "--exit-on-error", "--dbname", restored_database, str(dump)],
                       env=subprocess_env, check=True)
        with connect(profile, restored_database) as restored:
            assert before == database_fingerprint(restored), "Restored rows or sequences differ."
        manifest = {"createdAt": stamp, "sourceDatabase": profile["database"], "restoredDatabase": restored_database,
                    "dumpSha256": sha256(dump), "database": before, "media": media, "sources": sources,
                    "exactDatabaseAndSequencesMatch": True, "allStoredFilesMatch": True}
        (directory / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
        subprocess.run([sys.executable, __file__, "--verify-restore", str(directory)], check=True)
        assert before == database_fingerprint(original), "Restore verification modified the original database."
        assert media == file_manifest(VAR / "media") and sources == file_manifest(VAR / "source-databases")
    report = {"backupDirectory": str(directory), "restoredDatabase": restored_database,
              "tablesVerified": len(before["tables"]), "sequencesVerified": len(before["sequences"]),
              "privateFilesVerified": len(media), "sourceFilesVerified": len(sources),
              "exactDatabaseAndSequencesMatch": True, "originalDatabaseAndFilesUnchanged": True,
              "restoredApi": json.loads((directory / "restored-api-result.json").read_text())}
    (VAR / "restore-result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
