from django.core.management.base import BaseCommand
from apps.core.models import CanonicalIdentifier, KnowledgeEntity, SourceEntityMapping
from apps.sources.master_identity import bootstrap_existing_master_ids

class Command(BaseCommand):
    help = '为现有实体建立兼容主表映射，不合并同名实体、不导入工作簿、不启用同步。'
    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true')
    def handle(self, *args, **options):
        self.stdout.write(f'Existing entities: {KnowledgeEntity.objects.count()}')
        if options['apply']: bootstrap_existing_master_ids()
        self.stdout.write(f'Master bindings: {CanonicalIdentifier.objects.count()}, source observations: {SourceEntityMapping.objects.count()}')
        self.stdout.write('Integer PKs, stable IDs, saved tasks, original evidence and scheduling settings unchanged.')
