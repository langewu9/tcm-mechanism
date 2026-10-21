"""Real legacy disease workbook reconciliation in a disposable PostgreSQL DB.

prepare uses bundled Python's read-only openpyxl/pandas. compare uses the Django
venv and the existing importer, task and export APIs; never writes the work DB,
submits live queue messages, calls models/providers, or alters original files.
"""
import argparse
import ast
from collections import Counter
from contextlib import closing
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import subprocess
import sys
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
NODE = Path.home() / '.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node'
MAIN_REF = '078d374852d82ad398e98ff8e97d11f7eb2e3a62'
QUERIES = ['Cerebral Infarction', 'AIDS related dementia', 'Abdominal aortic aneurysm',
           'Diabetes mellitus', 'Pulmonary fibrosis', '肺纤维化']
FILES = {'diseaseHerbTarget':'疾病_中药.xlsx', 'diseaseTarget':'combined_results.xlsx'}


def clean(value):
    return '' if value is None else str(value).strip()


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def normalized(value):
    return re.sub(r'\s+', ' ', clean(value).casefold())


def main_frontend(cases, directory, name):
    references={}
    for source,filename in [('src/lib/disease-query.ts','main-disease-query.ts'),('src/app/api/research/route.ts','main-research-route.ts')]:
        data=subprocess.check_output(['git','show',f'{MAIN_REF}:{source}'],cwd=ROOT)
        path=directory/filename
        if path.exists(): assert path.read_bytes()==data
        else: path.write_bytes(data)
        references[source]={'path':str(path),'sha256':hashlib.sha256(data).hexdigest()}
    request = directory / f'{name}-input.json'
    request.write_text(json.dumps({'mainRef':MAIN_REF,'referenceFiles':references,'cases':cases},ensure_ascii=False))
    return json.loads(subprocess.check_output([str(NODE),str(ROOT/'tools/main_disease_reference.cjs'),str(request)],cwd=ROOT))


def prepare(args):
    import openpyxl
    import pandas as pd
    destination=args.output.resolve()
    if destination.exists(): raise ValueError('Refusing to overwrite an existing sample.')
    destination.parent.mkdir(parents=True,exist_ok=True)
    cases=main_frontend([{'query':q} for q in QUERIES],destination.parent,'main-aliases')['cases']
    terms={term.casefold() for case in cases for term in case['expandedQueries']}
    sample={'mainRef':MAIN_REF,'cases':cases,'files':[],'rows':[],'sourceChecksumsUnchanged':False}
    for kind,filename in FILES.items():
        path=args.inputs/filename
        before=sha(path)
        wb=openpyxl.load_workbook(path,read_only=True,data_only=False)
        sheet=wb.active
        headers=[clean(value) for value in next(sheet.iter_rows(values_only=True))]
        positions=[headers.index(key) for key in (['疾病','中药','靶点基因'] if kind=='diseaseHerbTarget' else ['疾病','靶点基因','来源文件'])]
        total,background=0,0
        counts=Counter(); blanks=Counter(); punct=0; selected_count=0
        for number,cells in enumerate(sheet.iter_rows(min_row=2),2):
            if not any(cell.value is not None for cell in cells): continue
            total+=1
            if any(cell.data_type=='f' for cell in cells): raise ValueError(f'Formula review required: {filename}:{number}')
            values=[clean(cells[index].value) for index in positions]
            disease=values[0]; target=values[2] if kind=='diseaseHerbTarget' else values[1]
            counts[disease]+=1
            for key,index in zip(['疾病','中药','靶点基因'] if kind=='diseaseHerbTarget' else ['疾病','靶点基因','来源文件'],positions):
                if not clean(cells[index].value): blanks[key]+=1
            punct+=bool(re.search(r'[;,，；/|]',target))
            matched=any(term in disease.casefold() for term in terms)
            if not matched and background>=50: continue
            if matched: selected_count+=1
            else: background+=1
            sample['rows'].append({'kind':kind,'row':number,'values':values,'isBackground':not matched})
        wb.close()
        assert sha(path)==before
        sample['files'].append({'kind':kind,'filename':filename,'sha256':before,'sheet':sheet.title,'headers':headers,
            'totalRows':total,'selectedRows':selected_count,'backgroundRows':background,'blankFields':dict(blanks),
            'punctuatedTargetCells':punct,'diseaseCounts':dict(counts)})
    # AST extracts the actual pinned backend functions, with only local frames/cache
    # injected. Source is Git-tracked code, not code from the supplied archive.
    code=subprocess.check_output(['git','show',f'{MAIN_REF}:backend/data_service.py'],cwd=ROOT)
    module=ast.parse(code.decode())
    names={'_clean','_contains','search_disease'}
    selected=[node for node in module.body if isinstance(node,ast.FunctionDef) and node.name in names]
    assert len(selected)==len(names)
    frames={}
    for kind in FILES:
        columns=['疾病','中药','靶点基因'] if kind=='diseaseHerbTarget' else ['疾病','靶点基因','来源文件']
        frames[kind]=pd.DataFrame([row['values'] for row in sample['rows'] if row['kind']==kind],columns=columns)
    namespace={'pd':pd,'re':re,'_like':lambda q:f'%{q.strip()}%',
               'load_disease_herb':lambda:frames['diseaseHerbTarget'],
               'load_disease_targets':lambda:frames['diseaseTarget']}
    exec(compile(ast.Module(body=selected,type_ignores=[]),'pinned-main-data-service.py','exec'),namespace)
    cache=destination.parent/'disease-sample.sqlite3'
    if cache.exists(): raise ValueError('Refusing to overwrite the derived SQLite source.')
    with closing(sqlite3.connect(cache)) as database, database:
        database.executescript('CREATE TABLE herb_component_target (herb TEXT, component TEXT, target TEXT);'
            'CREATE TABLE disease_herb_target (rowid INTEGER PRIMARY KEY,disease TEXT,herb TEXT,target TEXT);'
            'CREATE TABLE disease_target (rowid INTEGER PRIMARY KEY,disease TEXT,target TEXT,source TEXT);')
        for kind,table in [('diseaseHerbTarget','disease_herb_target'),('diseaseTarget','disease_target')]:
            database.executemany(f'INSERT INTO {table} VALUES (?,?,?,?)',[(row['row'],*row['values']) for row in sample['rows'] if row['kind']==kind])
    namespace['_cache']=lambda:None
    raw_cases=[]; limited=[]
    for case in cases:
        expanded=case['expandedQueries']
        high=[namespace['search_disease'](term,limit=50000) for term in expanded]
        low=[namespace['search_disease'](term,limit=100) for term in expanded]
        raw_cases.append({**case,'results':high}); limited.append({**case,'results':low})
    full=main_frontend(raw_cases,destination.parent,'main-excel-full')['cases']
    capped=main_frontend(limited,destination.parent,'main-excel-preview')['cases']
    namespace['_cache']=lambda:sqlite3.connect(f'{cache.as_uri()}?mode=ro',uri=True)
    cache_cases=[]
    for case in cases:
        results=[]
        for term in case['expandedQueries']:
            db=sqlite3.connect(f'{cache.as_uri()}?mode=ro',uri=True); db.row_factory=sqlite3.Row
            namespace['_cache']=lambda db=db:db
            try: results.append(namespace['search_disease'](term,limit=50000))
            finally: db.close()
        cache_cases.append({**case,'results':results})
    cached=main_frontend(cache_cases,destination.parent,'main-cache-full')['cases']
    for case,excel,preview,cached_case in zip(cases,full,capped,cached):
        case.update(mainExcel=excel['data'],mainPreview=preview['data'],mainCache=cached_case['data'])
    sample.update(sourceChecksumsUnchanged=True,mainCodeSha256=hashlib.sha256(code).hexdigest(),
                  sqliteFilename=cache.name,sqliteSha256=sha(cache))
    destination.write_text(json.dumps(sample,ensure_ascii=False,indent=2))
    print(json.dumps({'sample':str(destination),'rows':len(sample['rows']),'files':[{k:v for k,v in f.items() if k!='diseaseCounts'} for f in sample['files']]},ensure_ascii=False),flush=True)


def compare(args):
    from postgres_acceptance import APP, environment
    environment(); os.environ['CACHE_URL']=''
    sys.path.insert(0,str(APP))
    import django
    django.setup()
    from django.contrib.auth import get_user_model
    from django.core.serializers.json import DjangoJSONEncoder
    from django.db import connection, transaction
    from django.test import override_settings
    from rest_framework.test import APIClient
    from apps.core.models import AnalysisTask, DataSource, EvidenceRelation, KnowledgeEntity, SyncRun
    from apps.core.services.complete_evidence import canonical, digest
    from apps.core.tasks import run_complete_evidence_task
    from apps.sources.sqlite_sync import preview_sqlite_sync, apply_sqlite_sync, _row_entities_and_relations
    sample=json.loads(args.sample.read_text())
    cache=args.sample.parent/sample['sqliteFilename']
    assert sample['mainRef']==MAIN_REF and sha(cache)==sample['sqliteSha256']
    for item in sample['files']: assert sha(args.sample.parent/'inputs'/item['filename'])==item['sha256']
    assert connection.vendor=='postgresql' and connection.settings_dict['NAME']=='tcm_acceptance'
    def live_state():
        with transaction.atomic():
            with connection.cursor() as cur: cur.execute('SET TRANSACTION READ ONLY')
            content={model._meta.label:list(model.objects.order_by('pk').values())
                     for model in (AnalysisTask,DataSource,KnowledgeEntity,EvidenceRelation)}
            return digest(json.loads(json.dumps(content,cls=DjangoJSONEncoder)))
    before=live_state(); original=connection.settings_dict['NAME']
    connection.settings_dict.setdefault('TEST',{})['NAME']='test_real_disease_'+secrets.token_hex(6)
    created=False; report={'mainRef':MAIN_REF,'mainCodeSha256':sample['mainCodeSha256'],
        'sampleSha256':sha(args.sample),'sourceFiles':sample['files'],'cases':[],
        'verificationScope':'Original-row/provenance and normalized legacy lookup parity; not authority or biological identity verification.',
        'currentCodeSha256':{name:sha(ROOT/name) for name in (
            'python_app/apps/sources/sqlite_sync.py','python_app/apps/core/services/disease_evidence.py',
            'python_app/apps/core/services/herb_evidence.py','python_app/apps/core/views/disease_evidence.py')},
        'modelsOrProvidersCalled':False,'sourceDataImportedIntoWorkDB':False}
    try:
        connection.creation.create_test_db(verbosity=0,autoclobber=False,serialize=False); created=True
        user=get_user_model().objects.create_user(username='real-disease-audit-owner')
        other=get_user_model().objects.create_user(username='real-disease-audit-other')
        client=APIClient(); client.force_authenticate(user)
        configuration={'connector':'sqlite-herb-compound-target','databaseFile':cache.name,
            'table':'herb_component_target','herbColumn':'herb','compoundColumn':'component','targetColumn':'target',
            'targetCellMode':'single','diseaseTargetTable':'disease_target','diseaseColumn':'disease',
            'diseaseTargetColumn':'target','diseaseSourceColumn':'source','diseaseHerbTargetTable':'disease_herb_target',
            'diseaseHerbColumn':'disease','diseaseHerbHerbColumn':'herb','diseaseHerbTargetColumn':'target'}
        source=DataSource.objects.create(slug='legacy-real-disease-audit',name='TEMP real legacy disease sample',configuration=configuration)
        control=next(row for row in sample['rows'] if row['kind']=='diseaseTarget' and '/' in row['values'][1] and not row['isBackground'])
        single,_=_row_entities_and_relations(source,(control['kind'],control['row'],*control['values']))
        source.configuration={**configuration,'targetCellMode':'list'}
        split,_=_row_entities_and_relations(source,(control['kind'],control['row'],*control['values']))
        source.configuration=configuration
        single_targets=[item['label'] for item in single if item['entity_type']=='protein']
        split_targets=[item['label'] for item in split if item['entity_type']=='protein']
        assert single_targets==[control['values'][1]] and split_targets!=single_targets
        report['delimiterControl']={'file':FILES[control['kind']],'row':control['row'],'originalTarget':control['values'][1],
            'singleModeTargets':single_targets,'listModeTargets':split_targets,'listModeNotApplied':True}
        run=SyncRun.objects.create(source=source,requested_by=user)
        started=time.perf_counter()
        with override_settings(SQLITE_SOURCE_ROOT=str(cache.parent),SOURCE_SCHEDULED_PREVIEWS_ENABLED=False):
            preview_sqlite_sync(run); apply_sqlite_sync(run)
        report['import']={'rows':run.records_seen,'relations':EvidenceRelation.objects.count(),'entities':KnowledgeEntity.objects.count(),
            'seconds':round(time.perf_counter()-started,3),'targetCellMode':'single','originalRowIdsPreserved':True,
            'diseaseRowPolicy':run.release.metadata.get('diseaseRowPolicy')}
        # Independent original-row oracle: do not generate expected rows using
        # the importer under test, and retain one assertion for each source row.
        all_evidence=list(EvidenceRelation.objects.select_related('subject','object'))
        actual={(r.relation_type,r.metadata['sourceRowId']):(normalized(r.subject.label),normalized(r.object.label)) for r in all_evidence}
        expected={}
        for row in sample['rows']:
            d,second,third=row['values']; number=row['row']
            if row['kind']=='diseaseTarget':
                if d and second: expected[('disease_target',number)]=(normalized(d),normalized(second))
            elif d and second:
                expected[('disease_herb',number)]=(normalized(d),normalized(second))
                if third:
                    expected[('disease_herb_target',number)]=(normalized(d),normalized(third))
                    expected[('herb_disease_target',number)]=(normalized(second),normalized(third))
        assert len(actual)==len(all_evidence) and actual==expected, 'Imported original source row projection differs.'
        report['import']['independentRowProjectionMatches']=True
        for case in sample['cases']:
            started=time.perf_counter(); query=case['query']
            terms=[term.casefold() for term in case['expandedQueries']]
            relevant=[row for row in sample['rows'] if any(term in row['values'][0].casefold() for term in terms)]
            relevant_ids={kind:{row['row'] for row in relevant if row['kind']==kind} for kind in FILES}
            oracle={key:value for key,value in expected.items() if key[0]!='herb_disease_target' and key[1] in
                relevant_ids['diseaseTarget' if key[0]=='disease_target' else 'diseaseHerbTarget']}
            response=client.get('/api/v1/catalog/diseases/evidence-search/',{'query':query})
            assert response.status_code==200
            preview=response.data
            assert preview['expandedQueries']==case['expandedQueries']
            with patch('apps.core.tasks.run_complete_evidence_task.apply_async') as dispatch:
                queued=client.post('/api/v1/catalog/diseases/evidence-analyses/',{'query':query,'expectedResultSha256':preview['resultSha256']},format='json')
            assert queued.status_code==202 and dispatch.call_count==1
            task=AnalysisTask.objects.get(pk=queued.data['id'])
            assert run_complete_evidence_task(task.pk)['status']=='succeeded'
            task.refresh_from_db(); manifest=task.result['snapshot']
            rows=list(task.snapshot_rows.filter(table='evidenceRecords').values_list('payload',flat=True))
            projected={(row['relationType'],row['sourceRowId']):(normalized(row['subject']),normalized(row['object'])) for row in rows}
            assert len(projected)==len(rows) and projected==oracle, (query,'saved source identities differ')
            original_rows={(row['kind'],row['row']):row['values'] for row in relevant}
            source_files={row['row']:row['values'][2] for row in relevant if row['kind']=='diseaseTarget'}
            for row in rows:
                raw=original_rows['diseaseTarget' if row['relationType']=='disease_target' else 'diseaseHerbTarget',row['sourceRowId']]
                assert row['sourceDiseaseLabel']==raw[0]
                assert row['sourceTargetLabel']==raw[1 if row['relationType']=='disease_target' else 2]
                assert row['sourceHerbLabel']==(None if row['relationType']=='disease_target' else raw[1])
                if row['relationType']=='disease_target':
                    assert row.get('sourceFile')==source_files[row['sourceRowId']], (
                        query,'frozen original 来源文件 differs',row['sourceRowId'],source_files[row['sourceRowId']],row.get('sourceFile'))
            target_labels={normalized(row['object']) for row in rows if row['relationType'] in {'disease_target','disease_herb_target'}}
            herb_labels={normalized(row['object']) for row in rows if row['relationType']=='disease_herb'}
            assert target_labels=={normalized(v) for v in case['mainExcel']['targets']}, (query,'main Excel targets differ')
            assert herb_labels=={normalized(v) for v in case['mainExcel']['herbs']}, (query,'main Excel herbs differ')
            assert target_labels=={normalized(v) for v in case['mainCache']['targets']}, (query,'main cache targets differ')
            direct=Counter(tuple(row['values'])
                for row in relevant if row['kind']=='diseaseHerbTarget' and row['values'][2])
            links=list(task.snapshot_rows.filter(table='diseaseLinks',payload__relationType='disease_herb_target').values_list('payload',flat=True))
            assert Counter((row['sourceDiseaseLabel'],row['sourceHerbLabel'],row['sourceTargetLabel']) for row in links)==direct
            old_triples={(row['疾病'],row['中药'],row['靶点基因']) for row in case['mainExcel']['links'] if clean(row['靶点基因'])}
            assert set(direct)==old_triples, (query,'main triple identities differ')
            variants={}
            for row in relevant:
                target=row['values'][1 if row['kind']=='diseaseTarget' else 2]
                if target: variants.setdefault(normalized(target),set()).add(target)
            collisions=[{'lookupKey':key,'originalLabels':sorted(labels)} for key,labels in sorted(variants.items()) if len(labels)>1]
            base=f'/api/v1/research/analysis-tasks/{task.pk}'
            for table,info in manifest['tables'].items():
                exported=client.get(base+f'/snapshot-export/?table={table}&file_format=csv')
                assert exported.status_code==200
                csv_rows=list(csv.DictReader(io.StringIO(b''.join(exported.streaming_content).decode('utf-8-sig'))))
                assert len(csv_rows)==info['count']
                if table=='evidenceRecords':
                    csv_originals=Counter((row['relationType'],int(row['sourceRowId']),row['sourceDiseaseLabel'],row['sourceHerbLabel'],row['sourceTargetLabel'],row['sourceFile']) for row in csv_rows)
                    expected_originals=Counter((row['relationType'],row['sourceRowId'],row['sourceDiseaseLabel'] or '',row['sourceHerbLabel'] or '',row['sourceTargetLabel'] or '',row['sourceFile'] or '') for row in rows)
                    assert csv_originals==expected_originals,(query,'CSV original assertions differ')
                frozen=list(task.snapshot_rows.filter(table=table).values_list('payload',flat=True))
                assert hashlib.sha256(''.join(canonical(row)+'\n' for row in frozen).encode()).hexdigest()==info['sha256']
            hashes={name:hashlib.sha256() for name in manifest['tables']}; counts=Counter()
            exported=client.get(base+'/snapshot-export/')
            for chunk in exported.streaming_content:
                record=json.loads(chunk)
                if record['type']=='manifest':
                    meta=record['snapshot']; checksum=meta.pop('sha256')
                    assert checksum==digest({'parameters':record['parameters'],'result':record['result'],'manifest':meta})
                    continue
                name=record['table']; counts[name]+=1
                assert record['ordinal']==counts[name]
                hashes[name].update((canonical(record['payload'])+'\n').encode())
            assert all(counts[name]==info['count'] and hashes[name].hexdigest()==info['sha256'] for name,info in manifest['tables'].items())
            for page in {1,(len(rows)+19)//20}:
                result=client.get(base+f'/snapshot-rows/?table=evidenceRecords&page={page}&page_size=20')
                assert result.status_code==200 and result.data['count']==len(rows)
                assert result.data['results'][0]['ordinal']==(page-1)*20+1
            client.force_authenticate(other)
            assert client.get(base+'/snapshot-rows/').status_code==404 and client.get(base+'/snapshot-export/').status_code==404
            client.force_authenticate(user)
            item={'query':query,'rawDiseaseTargetRows':sum(row['kind']=='diseaseTarget' for row in relevant),
                'rawDiseaseHerbTargetRows':sum(row['kind']=='diseaseHerbTarget' for row in relevant),
                'mainPreviewCounts':case['mainPreview']['counts'],'mainFullCounts':case['mainExcel']['counts'],
                'completeCounts':task.result['counts'],'sourceRelations':len(rows),'previewRelations':preview['counts']['relations'],
                'previewTruncated':preview['truncated'],'snapshotSha256':manifest['sha256'],
                'sourceRowIdentityMatches':True,'originalSourceLabelsPreserved':True,
                'mainNormalizedTargetAndHerbNamesMatch':True,'mainOriginalUniqueTriplesMatch':True,
                'rawTargetNameCount':len(case['mainExcel']['targets']),'normalizedNameVariantGroups':collisions,
                'mainRawNameCountsIdentical':len(case['mainExcel']['targets'])==task.result['counts']['targets'],
                'biologicalIdentityVerified':False,
                'fullExportsAndHashesMatch':True,'paginationMatches':True,'otherAccountDenied':True,
                'seconds':round(time.perf_counter()-started,3)}
            report['cases'].append(item); print(json.dumps(item,ensure_ascii=False),flush=True)
    finally:
        if created: connection.creation.destroy_test_db(old_database_name=original,verbosity=0)
        else: connection.settings_dict['NAME']=original
    assert live_state()==before,'Work database changed during the disposable audit.'
    assert sha(cache)==sample['sqliteSha256']
    for item in sample['files']: assert sha(args.sample.parent/'inputs'/item['filename'])==item['sha256']
    report.update(passed=True,temporaryDatabaseDestroyed=True,workDatabaseUnchanged=True,derivedSourceUnchanged=True)
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    commands=parser.add_subparsers(dest='command',required=True)
    extract=commands.add_parser('prepare'); extract.add_argument('--inputs',type=Path,required=True); extract.add_argument('--output',type=Path,required=True)
    check=commands.add_parser('compare'); check.add_argument('--sample',type=Path,required=True); check.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.output.exists(): parser.error('Choose a new output; prior evidence must not be overwritten.')
    args.output.parent.mkdir(parents=True,exist_ok=True)
    prepare(args) if args.command=='prepare' else compare(args)


if __name__=='__main__': main()
