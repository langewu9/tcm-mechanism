import json
from django.core.management.base import BaseCommand,CommandError
from apps.sources.tcmsp_bundle import prepare_bundle
from apps.sources.tcmsp_publish import publish_bundle

class Command(BaseCommand):
    help='清洗、暂存或发布TCMSP补充数据；默认只暂存/预览。'
    def add_arguments(self,parser):
        parser.add_argument('directory');parser.add_argument('manifest');parser.add_argument('stage')
        parser.add_argument('--prepare',action='store_true');parser.add_argument('--apply',action='store_true')
    def handle(self,*args,**options):
        try:
            if options['prepare']:prepare_bundle(options['directory'],options['manifest'],options['stage'],progress=self.stdout.write)
            result=publish_bundle(options['stage'],options['directory'],options['manifest'],apply=options['apply'],progress=self.stdout.write)
        except ValueError as exc:raise CommandError(str(exc)) from exc
        self.stdout.write(json.dumps(result,ensure_ascii=False,indent=2))
