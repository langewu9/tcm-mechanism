"""Refresh SQLite index statistics after catalog index creation/import."""

from django.core.management.base import BaseCommand, CommandError
from django.db import connection


class Command(BaseCommand):
    help = "更新SQLite目录查询统计；仅写优化器元数据，不改变业务记录。不适用于PostgreSQL。"

    def add_arguments(self, parser):
        parser.add_argument("--sample-limit", type=int, default=0,
            help="每个索引的抽样上限；默认0读取完整索引统计，适合关系分布高度不均的原库。")

    def handle(self, *args, **options):
        if connection.vendor != "sqlite":
            self.stdout.write("Skipped: SQLite planner maintenance only.")
            return
        if options["sample_limit"] < 0:
            raise CommandError("sample-limit must be nonnegative")
        tables = ("core_knowledgeentity", "core_sourceentitymapping", "core_evidencerelation")
        required = {"entity_exact_name_idx", "mapping_exact_name_idx", "evidence_subject_type_idx", "evidence_object_type_idx"}
        with connection.cursor() as cursor:
            existing = set()
            for table in tables:
                cursor.execute(f"PRAGMA index_list({table})")
                existing.update(row[1] for row in cursor.fetchall())
            if missing := required - existing:
                raise CommandError(f"Apply core.0024_catalog_lookup_indexes first; missing: {sorted(missing)}")
            cursor.execute("PRAGMA analysis_limit")
            previous_limit = cursor.fetchone()[0]
            try:
                # Full index statistics avoid underestimating the few very
                # frequent relation types; optional sampling is explicit.
                cursor.execute(f"PRAGMA analysis_limit={int(options['sample_limit'])}")
                for table in tables:
                    cursor.execute(f"ANALYZE {table}")
                    self.stdout.write(f"Updated planner statistics: {table}")
            finally:
                cursor.execute(f"PRAGMA analysis_limit={int(previous_limit)}")
