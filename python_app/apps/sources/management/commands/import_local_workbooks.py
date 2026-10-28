import json
import os
from pathlib import Path
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.test.utils import override_settings
from apps.sources.legacy_workbooks import SOURCES
from apps.sources.workbook_import import import_workbook


class Command(BaseCommand):
    help = "显式导入已授权内部使用的七份工作簿；完整验收后发布，不启用定时同步。"

    def add_arguments(self, parser):
        parser.add_argument("--directory", required=True)
        parser.add_argument("--source", choices=["all", *SOURCES], default="all")
        parser.add_argument("--apply", action="store_true")

    def handle(self, *args, **options):
        directory = Path(options["directory"]).resolve(strict=True)
        slugs = list(SOURCES) if options["source"] == "all" else [options["source"]]
        for slug in slugs:
            if not (directory / SOURCES[slug].filename).is_file():
                raise CommandError(f"Required workbook missing: {SOURCES[slug].filename}")
        lock = settings.BASE_DIR / "var" / "workbook-import.lock"
        lock.parent.mkdir(parents=True, exist_ok=True)
        try:
            descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            raise CommandError("Another workbook import lock exists; inspect its process before retrying.")
        try:
            os.write(descriptor, str(os.getpid()).encode())
            os.close(descriptor)
            # Do not retain millions of debug SQL strings during bulk ingestion.
            with override_settings(DEBUG=False):
                for slug in slugs:
                    result = import_workbook(directory, slug, apply=options["apply"], progress=self.stdout.write)
                    self.stdout.write(json.dumps(result, ensure_ascii=False, sort_keys=True))
        finally:
            lock.unlink()
