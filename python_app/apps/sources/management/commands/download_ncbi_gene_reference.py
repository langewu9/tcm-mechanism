import json

from django.core.management.base import BaseCommand, CommandError

from apps.sources.connectors.ncbi_gene_reference import download_reference


class Command(BaseCommand):
    help = "下载并校验 NCBI 官方人类 Gene 符号与别名参考文件。"

    def add_arguments(self, parser):
        parser.add_argument("--directory", default="/app/var/target-reference")

    def handle(self, *args, **options):
        try:
            path = download_reference(options["directory"])
        except (OSError, ValueError) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(json.dumps({"manifest": str(path)}, ensure_ascii=False))
