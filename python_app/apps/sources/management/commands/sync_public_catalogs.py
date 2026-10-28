"""Import one frozen official snapshot; never send uploaded research data."""
from django.core.management.base import BaseCommand
from django.utils import timezone
from apps.core.models import DataSource, SyncRun
from apps.sources import services

class Command(BaseCommand):
    help = '同步完整的 UniProt 审核人类蛋白目录与 Reactome 人类通路目录；默认预览。'

    def add_arguments(self, parser):
        parser.add_argument('--source', choices=['all', 'uniprot-human', 'reactome'], default='all')
        parser.add_argument('--apply', action='store_true')

    def handle(self, *args, **options):
        slugs = ['uniprot-human', 'reactome'] if options['source'] == 'all' else [options['source']]
        for slug in slugs:
            source = DataSource.objects.get(slug=slug)
            if not source.enabled:
                self.stderr.write(f'{slug}: disabled; not changed')
                continue
            run = SyncRun.objects.create(source=source, status='running', started_at=timezone.now())
            try:
                if slug == 'uniprot-human':
                    self.stdout.write('Fetching full reviewed human UniProt catalogue…')
                    snapshot = services._get_uniprot_snapshot()
                    services.preview_uniprot_sync(run, snapshot=snapshot)
                    if options['apply']: services.apply_uniprot_sync(run, snapshot=snapshot)
                else:
                    self.stdout.write('Fetching full human Reactome pathway catalogue…')
                    snapshot = services._get_snapshot()
                    services.preview_reactome_sync(run, snapshot=snapshot)
                    if options['apply']: services.apply_reactome_sync(run, snapshot=snapshot)
                run.status = 'succeeded'
                run.finished_at = timezone.now()
                run.save(update_fields=['status', 'finished_at'])
                self.stdout.write(f'{slug}: rows={run.records_seen}, version={run.release.version}, mode={"apply" if options["apply"] else "preview"}')
            except Exception as exc:
                run.status = 'failed'
                run.error_summary = str(exc)[:1000]
                run.finished_at = timezone.now()
                run.save(update_fields=['status', 'error_summary', 'finished_at'])
                raise
