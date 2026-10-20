"""Compare real PostgreSQL plans on disposable synthetic temporary tables.

Requires the local isolated PG acceptance profile. Does not create research
records or persistent indexes. All temporary writes are rolled back on exit.
"""
import argparse
import json
import statistics
import sys

from postgres_acceptance import APP, environment


def measure(cursor, sql):
    # One warm-up plus three measured plans; retain a representative actual plan.
    plans = []
    for _ in range(4):
        cursor.execute("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + sql)
        plans.append(cursor.fetchone()[0][0])
    measured = plans[1:]
    representative = sorted(measured, key=lambda plan: plan["Execution Time"])[1]
    return {
        "medianExecutionMs": statistics.median(plan["Execution Time"] for plan in measured),
        "plan": representative,
    }


def remove_candidate_copies(cursor, connection, table, signatures):
    """Reproduce the old index baseline even after the migration is applied."""
    cursor.execute("""SELECT c.relname, pg_get_indexdef(i.indexrelid)
        FROM pg_index i JOIN pg_class c ON c.oid=i.indexrelid
        WHERE i.indrelid=to_regclass(%s)""", [table])
    for name, definition in cursor.fetchall():
        if any(signature in definition for signature in signatures):
            cursor.execute("DROP INDEX " + connection.ops.quote_name(name))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rows", type=int, default=60000)
    args = parser.parse_args()
    if not 20000 <= args.rows <= 120000:
        parser.error("rows must be between 20,000 and 120,000")
    environment()
    sys.path.insert(0, str(APP))
    import django
    django.setup()
    from django.db import connection

    report = {"synthetic": True, "rowsPerTable": args.rows, "users": 200, "sources": 40,
              "temporaryTablesOnly": True, "warmupRuns": 1, "measuredRuns": 3}
    connection.set_autocommit(False)
    try:
        with connection.cursor() as cursor:
            cursor.execute("SET LOCAL statement_timeout = '30s'")
            cursor.execute("SELECT version()")
            report["server"] = cursor.fetchone()[0]
            cursor.execute("CREATE TEMP TABLE perf_tasks (LIKE core_analysistask INCLUDING ALL) ON COMMIT DROP")
            remove_candidate_copies(cursor, connection, "perf_tasks", [
                "(owner_id, created_at DESC, id DESC)", "(created_at DESC, id DESC)",
            ])
            cursor.execute("""INSERT INTO perf_tasks
                (id, owner_id, task_type, status, input_parameters, progress, result, error_summary, created_at)
                SELECT n, 1+(n%%200),
                    CASE (n/200)%%3 WHEN 0 THEN 'proteomics' WHEN 1 THEN 'network' ELSE 'visualization' END,
                    CASE n%%4 WHEN 0 THEN 'queued' ELSE 'succeeded' END,
                    jsonb_build_object('name','Synthetic task', 'chartKey','proteomics_summary', 'snapshot',repeat(md5(n::text),20)),
                    100, jsonb_build_object('synthetic',true,'payload',repeat(md5(n::text),40)), '',
                    now()-(((n*7919)%%(%s)) * interval '1 second')
                FROM generate_series(1,%s) n""", [args.rows, args.rows])
            cursor.execute("CREATE TEMP TABLE perf_syncs (LIKE core_syncrun INCLUDING ALL) ON COMMIT DROP")
            remove_candidate_copies(cursor, connection, "perf_syncs", ["(source_id, created_at DESC, id DESC)"])
            cursor.execute("""INSERT INTO perf_syncs
                (id,source_id,status,trigger,cursor,records_seen,records_created,records_updated,records_retired,
                 error_summary,preview_summary,created_at)
                SELECT n,1+(n%%40),'succeeded','manual','',100,100,0,0,'',
                    jsonb_build_object('synthetic',true,'preview',repeat(md5(n::text),10)),
                    now()-(((n*7919)%%(%s)) * interval '1 second')
                FROM generate_series(1,%s) n""", [args.rows, args.rows])
            cursor.execute("ANALYZE perf_tasks")
            cursor.execute("ANALYZE perf_syncs")
            queries = {
                "userTasks": "SELECT id,owner_id,task_type,status,created_at FROM perf_tasks WHERE owner_id=42 ORDER BY created_at DESC,id DESC LIMIT 50",
                "userProteomics": "SELECT id,owner_id,task_type,status,created_at FROM perf_tasks WHERE owner_id=42 AND task_type='proteomics' ORDER BY created_at DESC,id DESC LIMIT 50",
                "adminTasks": "SELECT id,owner_id,task_type,status,created_at FROM perf_tasks ORDER BY created_at DESC,id DESC LIMIT 50",
                "sourceHistory": "SELECT id,source_id,status,created_at FROM perf_syncs WHERE source_id=12 ORDER BY created_at DESC,id DESC LIMIT 50",
            }
            report["before"] = {name: measure(cursor, query) for name, query in queries.items()}
            cursor.execute("SELECT pg_indexes_size('perf_tasks'),pg_indexes_size('perf_syncs')")
            report["indexBytesBefore"] = dict(zip(("tasks", "syncs"), cursor.fetchone()))
            cursor.execute("CREATE INDEX perf_task_owner_created_idx ON perf_tasks(owner_id,created_at DESC,id DESC)")
            cursor.execute("CREATE INDEX perf_task_created_idx ON perf_tasks(created_at DESC,id DESC)")
            cursor.execute("CREATE INDEX perf_sync_source_created_idx ON perf_syncs(source_id,created_at DESC,id DESC)")
            cursor.execute("ANALYZE perf_tasks")
            cursor.execute("ANALYZE perf_syncs")
            report["after"] = {name: measure(cursor, query) for name, query in queries.items()}
            cursor.execute("SELECT pg_indexes_size('perf_tasks'),pg_indexes_size('perf_syncs')")
            report["indexBytesAfter"] = dict(zip(("tasks", "syncs"), cursor.fetchone()))
    finally:
        connection.rollback()
        connection.close()
    output = APP / "var/database-performance-audit"
    output.mkdir(parents=True, exist_ok=True)
    (output / "benchmarks.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps({name: {"beforeMs": report["before"][name]["medianExecutionMs"],
                              "afterMs": report["after"][name]["medianExecutionMs"]}
                      for name in report["before"]}, indent=2))
    print("Only temporary tables used; transaction rolled back.")


if __name__ == "__main__":
    main()
