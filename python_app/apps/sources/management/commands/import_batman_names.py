import json
from django.core.management.base import BaseCommand
from apps.sources.supplemental_names import import_batman_names


class Command(BaseCommand):
    help = 'Preview or publish source-local BATMAN retrieval aliases, preserving raw rows.'

    def add_arguments(self, parser):
        parser.add_argument('workbook')
        parser.add_argument('--apply', action='store_true')

    def handle(self, *args, **options):
        self.stdout.write(json.dumps(import_batman_names(options['workbook'], apply=options['apply']), ensure_ascii=False, indent=2))
