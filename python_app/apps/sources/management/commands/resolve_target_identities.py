import json
from django.core.management.base import BaseCommand, CommandError
from apps.sources.target_identity import build_target_identities

class Command(BaseCommand):
    help = '核验标准靶点编号并建立可追溯映射；默认只预览，不合并原主键或启用同步。'
    def add_arguments(self, parser):
        parser.add_argument('manifest'); parser.add_argument('--ncbi-manifest')
        parser.add_argument('--ncbi-taxonomy-manifest')
        parser.add_argument('--uniprot-taxonomy-manifest')
        parser.add_argument('--apply', action='store_true')
    def handle(self, *args, **options):
        try: result = build_target_identities(options['manifest'],
            ncbi_gene_manifest_path=options['ncbi_manifest'],
            ncbi_taxonomy_manifest_path=options['ncbi_taxonomy_manifest'],
            uniprot_taxonomy_manifest_path=options['uniprot_taxonomy_manifest'], apply=options['apply'])
        except ValueError as exc: raise CommandError(str(exc)) from exc
        self.stdout.write(json.dumps(result, ensure_ascii=False, indent=2))
