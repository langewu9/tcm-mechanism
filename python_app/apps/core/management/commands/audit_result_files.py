"""Print a bounded, read-only local inventory; never reconcile or delete."""
import json

from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from apps.core.services.result_file_audit import audit_result_files


class Command(BaseCommand):
    help = "Read-only audit of published artifacts, uploaded originals and unregistered local file candidates. Never deletes or retries."
    requires_system_checks = []

    def add_arguments(self, parser):
        parser.add_argument("--max-records", type=int, default=10000)
        parser.add_argument("--max-files", type=int, default=10000, help="Maximum filesystem entries including directories.")
        parser.add_argument("--max-findings", type=int, default=200)
        parser.add_argument("--max-bytes", type=int, default=2 * 1024**3)

    def handle(self, *args, **options):
        try:
            with transaction.atomic():
                if connection.vendor == "postgresql":
                    with connection.cursor() as cursor:
                        cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
                report = audit_result_files(**{name: options[name] for name in (
                    "max_records", "max_files", "max_findings", "max_bytes")})
        except ValueError as error:
            raise CommandError(str(error)) from error
        self.stdout.write(json.dumps(report, ensure_ascii=False))
