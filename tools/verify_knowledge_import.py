"""Verify the actual local knowledge import, sampled origins and one full HTTP query.

Retains one real disease analysis for the existing researcher A. No synthetic
knowledge, model/provider calls, old research rewrites, or external transmission.
"""
import argparse
from collections import Counter
from contextlib import closing
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import random
import re
import sqlite3
import subprocess
import sys

from postgres_acceptance import APP,VAR,PG_BIN,environment
from smoke_local_workspace import LocalClient,wait_task


def sha(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def canonical(value):return json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False)


def norm(value):return re.sub(r'\s+',' ',value.strip().casefold())


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--manifest',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.output.exists():raise ValueError('Refusing to replace earlier proof.')
    environment();sys.path.insert(0,str(APP))
    import django;django.setup()
    from django.conf import settings
    from django.core.serializers.json import DjangoJSONEncoder
    from django.db import connection
    from apps.core.models import DataSource,EvidenceRelation,KnowledgeEntity,EntityIdentifier,AnalysisTask,ResearchDataset,MedicalCase,VisualizationArtifact
    state=json.loads((args.manifest.parent/'apply-state.json').read_text());assert state['complete'] and state['researchUnchanged']
    manifest=json.loads(args.manifest.read_text());assert manifest['complete']
    assert connection.settings_dict['NAME']=='tcm_acceptance'
    def research_unchanged():
        for model in (AnalysisTask,ResearchDataset,MedicalCase,VisualizationArtifact):
            original=state['researchBefore'][model._meta.label]
            for row in model.objects.filter(pk__in=[int(pk) for pk in original]).values():
                plain=json.loads(json.dumps(row,cls=DjangoJSONEncoder))
                assert hashlib.sha256(canonical(plain).encode()).hexdigest()==original[str(row['id'])]
    research_unchanged()
    report={'scope':__doc__,'sources':[],'modelOrProviderCalls':False,'samples':0}
    # Only read PK/stable-ID pairs from the private pre-import backup; do not
    # restore over the working DB or print the private backup contents.
    backup=json.loads((args.manifest.parent/'backup.json').read_text())
    backup_path=args.manifest.parent/backup['file'];assert sha(backup_path)==backup['sha256']
    dump=subprocess.check_output([str(PG_BIN/'pg_restore'),'--data-only','--table=core_knowledgeentity','--file=-',str(backup_path)],env=os.environ)
    original_ids={};columns=None
    for line in dump.decode().splitlines():
        if line.startswith('COPY public.core_knowledgeentity ('):
            columns=line.split('(',1)[1].split(')',1)[0].split(', ');continue
        if columns is not None:
            if line==r'\.':break
            fields=line.split('\t');original_ids[int(fields[columns.index('id')])]=fields[columns.index('stable_id')]
    assert original_ids
    assert dict(KnowledgeEntity.objects.filter(pk__in=original_ids).values_list('pk','stable_id'))==original_ids
    report['originalKnowledgeEntityIdsPreserved']=len(original_ids)
    for entry,applied in zip(manifest['sources'],state['sources']):
        assert entry['provider']==applied['provider'] and applied['phase']=='succeeded'
        provider=entry['provider'];source=DataSource.objects.get(pk=applied['sourceId']);release=applied['sourceReleaseId']
        assert source.enabled and source.last_success_at and source.configuration['databaseFile']==entry['databaseFile']
        assert KnowledgeEntity.objects.filter(source_release__source=source,is_active=True).count()==applied['activeEntities']
        assert EvidenceRelation.objects.filter(source_release_id=release,is_active=True).count()==applied['activeRelations']
        assert not KnowledgeEntity.objects.filter(source_release__source=source,is_active=True).exclude(organism='').exists()
        assert not EntityIdentifier.objects.filter(entity__source_release__source=source).exists()
        path=Path(settings.SQLITE_SOURCE_ROOT)/entry['databaseFile'];assert sha(path)==entry['sqliteSha256']
        for workbook in entry['workbooks']:assert sha(args.manifest.parent/'inputs'/workbook['file'])==workbook['sha256']
        expected={};sampled=0
        with closing(sqlite3.connect(f'{path.as_uri()}?mode=ro',uri=True)) as db:
            for table,kind in [('herb_component_target','herb'),('disease_herb_target','diseaseHerbTarget'),('disease_target','diseaseTarget')]:
                low,high=db.execute(f'SELECT MIN(rowid),MAX(rowid) FROM {table}').fetchone()
                if low is None:continue
                rng=random.Random(entry['sqliteSha256']+kind)
                keys={low,high,*[rng.randint(low,high) for _ in range(18)]};rows={}
                for key in keys:
                    row=db.execute(f'SELECT * FROM {table} WHERE rowid>=? ORDER BY rowid LIMIT 1',(key,)).fetchone()
                    rows[row[0]]=row
                for number,first,second,third,encoded in rows.values():
                    metadata=json.loads(encoded);sampled+=1
                    target=third if kind!='diseaseTarget' else second
                    identity=metadata['identity']
                    suffix=hashlib.sha256((identity['targetId'] if provider=='hit' else norm(target)).encode()).hexdigest()
                    ids=[]
                    if kind=='herb':
                        if first and second:ids.append((f'herb:{number}:herb-compound','contains'))
                        if second and third:ids.append((f'herb:{number}:compound-target:{suffix}','targets'))
                    elif kind=='diseaseTarget':
                        if first and second:ids.append((f'diseaseTarget:{number}:{suffix}','disease_target'))
                    elif first and second:
                        ids.append((f'diseaseHerbTarget:{number}:herb','disease_herb'))
                        if third:ids.extend([(f'diseaseHerbTarget:{number}:disease-target:{suffix}','disease_herb_target'),(f'diseaseHerbTarget:{number}:herb-target:{suffix}','herb_disease_target')])
                    for record_id,kind_name in ids:expected[record_id]=(kind_name,metadata)
        actual={row.source_record_id:row for row in EvidenceRelation.objects.filter(source_release_id=release,source_record_id__in=expected).order_by()}
        assert set(actual)==set(expected),(provider,'sample record IDs differ')
        for record_id,(kind,metadata) in expected.items():
            row=actual[record_id]
            assert row.relation_type==kind and row.metadata['sourceRowId']==metadata['sourceRow']
            assert row.metadata['sourceOrigin']=={key:metadata[key] for key in ('workbookSha256','sheet','sourceRow')}
            assert row.metadata['sourceIdentity']==metadata['identity'] and row.metadata['rawFields']==metadata['rawFields']
        report['samples']+=sampled
        report['sources'].append({'provider':provider,'sourceId':source.pk,'sourceReleaseId':release,'inputRows':applied['inputRows'],
            'activeEntities':applied['activeEntities'],'activeRelations':applied['activeRelations'],'quarantinedRows':entry['quarantinedRows'],
            'sampledOriginalRows':sampled,'sampledRelationIds':len(expected),'allSampleOriginsMatch':True,'originalWorkbooksUnchanged':True})
    accounts=json.loads((VAR/'accounts.json').read_text())
    client=LocalClient(accounts['a'],base_url='http://127.0.0.1:5174',csrf_cookie_name='tcm_pg_csrf')
    other=LocalClient(accounts['b'],base_url='http://127.0.0.1:5174',csrf_cookie_name='tcm_pg_csrf')
    client.request('/api/v1/admin/sources/',expected=403)
    _,preview=client.request('/api/v1/catalog/diseases/evidence-search/?query=%E8%82%BA%E7%BA%A4%E7%BB%B4%E5%8C%96')
    assert preview['matches'] and preview['truncated']
    assert preview['expandedQueries']==['肺纤维化','Pulmonary fibrosis','Idiopathic pulmonary fibrosis','Interstitial lung disease']
    _,queued=client.request('/api/v1/catalog/diseases/evidence-analyses/',method='POST',expected=202,
        data={'query':'肺纤维化','expectedResultSha256':preview['resultSha256']})
    task=wait_task(client,queued['id']);assert task['status']=='succeeded'
    assert task['result']['counts']=={'diseases':1,'herbs':296,'targets':8325,'links':25855,'relations':25855}
    base=f'/api/v1/research/analysis-tasks/{task["id"]}'
    _,data=client.request(base+'/snapshot-export/?table=evidenceRecords&file_format=csv')
    rows=list(csv.DictReader(io.StringIO(data.decode('utf-8-sig'))))
    assert len(rows)==25855 and all(row['sourceOrigin'] and row['sourceTargetLabel'] is not None for row in rows)
    _,full=client.request(base+'/snapshot-export/?file_format=jsonl')
    parsed=[json.loads(line) for line in full.decode().splitlines()]
    for name,info in task['result']['snapshot']['tables'].items():
        records=[row['payload'] for row in parsed[1:] if row['table']==name]
        assert len(records)==info['count']
        assert hashlib.sha256(''.join(canonical(row)+'\n' for row in records).encode()).hexdigest()==info['sha256']
    other.request(base+'/',expected=404);other.request(base+'/snapshot-export/',expected=404)
    _,herb=client.request('/api/v1/catalog/herb-evidence/batch/',method='POST',data={'queryType':'herb','queries':['石榴皮']})
    assert herb['results'][0]['herbs'] and herb['results'][0]['relations']
    assert all(row['sourceOrigin'] for row in herb['results'][0]['relations'])
    research_unchanged()
    report.update(complete=True,fullDiseaseTaskId=task['id'],diseaseCounts=task['result']['counts'],diseaseSnapshotSha256=task['result']['snapshot']['sha256'],
                  fullDiseaseCsvRows=len(rows),privateDownloadVerified=True,oldResearchUnchanged=True,
                  totalInputRows=sum(row['inputRows'] for row in report['sources']),totalActiveRelations=sum(row['activeRelations'] for row in report['sources']),
                  totalActiveEntities=sum(row['activeEntities'] for row in report['sources']))
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2));args.output.chmod(0o600)
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
