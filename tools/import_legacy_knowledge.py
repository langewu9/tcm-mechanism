"""Import user-supplied original knowledge files into the local PostgreSQL workspace.

prepare: bundled Python, read-only Excel extraction into immutable derived SQLite.
apply: Django venv, existing preview/apply task code, with a required local backup.
No external calls, inferred identifiers, source workbook edits, or research rewrites.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import logging
import math
import os
from pathlib import Path
import sqlite3
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.source_catalog import SOURCE_FILES

VERSION = 'legacy-workbooks-full-1'
IDENTITY_COLUMNS = {'herbId':'Herb ID','compoundId':'Compound Id','targetId':'Target ID',
                    'targetSymbol':'Symbol','uniprot':'Uniprot','pubchem':'Pubchem ID','chembl':'Chembl ID'}


def clean(value): return '' if value is None else str(value).strip()


def sha(path):
    with Path(path).open('rb') as stream: return hashlib.file_digest(stream,'sha256').hexdigest()


def save(path, value):
    temporary=path.with_suffix(path.suffix+'.partial')
    temporary.write_text(json.dumps(value,ensure_ascii=False,indent=2))
    temporary.chmod(0o600); temporary.replace(path)


def log(**values): print(json.dumps(values,ensure_ascii=False),flush=True)


def prepare(args):
    import openpyxl
    args.output_root.mkdir(parents=True,exist_ok=True)
    manifest={'version':VERSION,'sources':[],'complete':False}
    inventory=json.loads((ROOT/'python_app/var/legacy-workbook-inventory.json').read_text())
    expected={item['file']:item['sha256'] for item in inventory}
    for item in json.loads((ROOT/'python_app/var/disease-real-2026-10-21/inputs/manifest.json').read_text())['files']:
        expected[item['file']]=item['sha256']
    groups=[('disease',[('diseaseHerbTarget','疾病_中药.xlsx'),('diseaseTarget','combined_results.xlsx')])]
    groups += [(key,[('herb',SOURCE_FILES[key]['file'])]) for key in ['tcmsp','hit','batman','tcmip','herb']]
    for provider, files in groups:
        tag=hashlib.sha256(json.dumps([(name,expected[name]) for _,name in files]).encode()).hexdigest()[:12]
        destination=args.output_root/f'legacy-full-{provider}-{tag}-v1.sqlite3'
        sidecar=destination.with_suffix('.manifest.json')
        if sidecar.exists():
            entry=json.loads(sidecar.read_text())
            assert entry['version']==VERSION and sha(destination)==entry['sqliteSha256']
            manifest['sources'].append(entry); save(args.manifest,manifest); log(provider=provider,status='reused-prepared'); continue
        if destination.exists(): raise ValueError('Unregistered derived source exists; refusing overwrite.')
        partial=destination.with_suffix('.sqlite3.partial')
        if partial.exists(): raise ValueError('Interrupted staging file exists; inspect it before retrying.')
        quarantine=args.manifest.parent/f'{provider}-quarantine.jsonl'
        if quarantine.exists(): raise ValueError('Refusing overwrite of an earlier quarantine.')
        entry={'version':VERSION,'provider':provider,'databaseFile':destination.name,'workbooks':[],
               'quarantineFile':quarantine.name,'quarantinedRows':0,'quarantineReasons':{},'targetCellMode':'single'}
        quality=Counter(); problems=Counter(); proofs={}; conflicts=set()
        database=sqlite3.connect(partial)
        database.executescript('CREATE TABLE herb_component_target(rowid INTEGER PRIMARY KEY,herb TEXT,component TEXT,target TEXT,extra TEXT);'
            'CREATE TABLE disease_herb_target(rowid INTEGER PRIMARY KEY,disease TEXT,herb TEXT,target TEXT,extra TEXT);'
            'CREATE TABLE disease_target(rowid INTEGER PRIMARY KEY,disease TEXT,target TEXT,source TEXT,extra TEXT);')
        with quarantine.open('x') as rejected:
            quarantine.chmod(0o600)
            for kind, filename in files:
                workbook_path=args.inputs/filename
                assert sha(workbook_path)==expected[filename], 'Original workbook checksum differs.'
                book=openpyxl.load_workbook(workbook_path,read_only=True,data_only=False); sheet=book.active
                headers=[clean(value) for value in next(sheet.iter_rows(values_only=True))]
                if kind=='herb': columns=[SOURCE_FILES[provider][key] for key in ('herb','component','target')]
                else: columns=['疾病','中药','靶点基因'] if kind=='diseaseHerbTarget' else ['疾病','靶点基因','来源文件']
                positions=[headers.index(name) for name in columns]
                count=0; accepted=0; buffer=[]
                table={'herb':'herb_component_target','diseaseHerbTarget':'disease_herb_target','diseaseTarget':'disease_target'}[kind]
                for row_number,cells in enumerate(sheet.iter_rows(min_row=2),2):
                    if not any(cell.value is not None for cell in cells): continue
                    count+=1; raw={key:cell.value for key,cell in zip(headers,cells)}
                    values=[clean(cells[index].value) for index in positions]
                    reason=''
                    if any(cell.data_type=='f' for cell in cells): reason='formula_requires_review'
                    elif any(v is not None and (type(v) not in (str,int,float,bool) or (type(v) is float and not math.isfinite(v))) for v in raw.values()): reason='unsupported_raw_value'
                    elif any('\x00' in v for v in raw.values() if isinstance(v,str)): reason='nul_requires_review'
                    elif any(len(v)>300 for v in values[:2 if kind=='diseaseTarget' else 3]): reason='oversized_entity_label'
                    if any(not value for value in values): quality[kind+':missing_field_rows']+=1
                    identity={}
                    if provider=='hit':
                        identity={key:clean(raw[column]) for key,column in IDENTITY_COLUMNS.items()}
                        if not all(values): reason=reason or 'pending_missing_entity_label'
                        if not all(identity[key] for key in ('herbId','compoundId','targetId')): reason=reason or 'missing_source_identifier'
                        if any(len(value)>160 for value in identity.values()): reason=reason or 'oversized_source_identifier'
                    metadata={'schemaVersion':'legacy-source-identity-1' if provider=='hit' else 'legacy-source-row-1',
                              'workbookSha256':expected[filename],'sheet':sheet.title,'sourceRow':row_number,
                              'identity':identity,'rawFields':raw}
                    encoded=json.dumps(metadata,ensure_ascii=False,allow_nan=False,default=str)
                    if len(encoded.encode())>65536: reason=reason or 'oversized_row_metadata'
                    if reason:
                        rejected.write(json.dumps({'file':filename,'row':row_number,'reason':reason,'original':metadata},ensure_ascii=False,default=str)+'\n')
                        problems[reason]+=1; continue
                    if provider=='hit':
                        for entity_kind,id_key,label,refs in [('herb','herbId',values[0],()),('compound','compoundId',values[1],(identity['pubchem'],identity['chembl'])),('target','targetId',values[2],(identity['uniprot'],identity['targetSymbol']))]:
                            key=(entity_kind,identity[id_key]); proof=(label,refs)
                            if key in proofs and proofs[key]!=proof: conflicts.add(key)
                            else: proofs[key]=proof
                    buffer.append((row_number,*values,encoded)); accepted+=1
                    if len(buffer)==1000:
                        database.executemany(f'INSERT INTO {table} VALUES(?,?,?,?,?)',buffer); buffer.clear()
                    if count%50000==0: log(provider=provider,file=filename,rowsRead=count,phase='prepare')
                if buffer: database.executemany(f'INSERT INTO {table} VALUES(?,?,?,?,?)',buffer)
                database.commit(); book.close()
                assert sha(workbook_path)==expected[filename]
                entry['workbooks'].append({'file':filename,'kind':kind,'sha256':expected[filename],'sheet':sheet.title,'headers':headers,'dataRows':count,'acceptedBeforeIdentityReview':accepted})
            if conflicts:
                ids=[]
                for row_id,encoded in database.execute('SELECT rowid,extra FROM herb_component_target'):
                    data=json.loads(encoded); identity=data['identity']
                    if any((kind,identity[key]) in conflicts for kind,key in [('herb','herbId'),('compound','compoundId'),('target','targetId')]):
                        ids.append((row_id,)); problems['conflicting_source_identifier']+=1
                        rejected.write(json.dumps({'file':files[0][1],'row':row_id,'reason':'conflicting_source_identifier','original':data},ensure_ascii=False)+'\n')
                database.executemany('DELETE FROM herb_component_target WHERE rowid=?',ids); database.commit()
                entry['conflictingIdentifierGroups']=len(conflicts)
        entry.update(tableRows={table:database.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0] for table in ('herb_component_target','disease_herb_target','disease_target')},
                     quarantinedRows=sum(problems.values()),quarantineReasons=dict(problems),quality=dict(quality),completeInputRead=True)
        database.execute('CREATE TABLE source_manifest(key TEXT PRIMARY KEY,value TEXT)')
        database.executemany('INSERT INTO source_manifest VALUES(?,?)',[(key,json.dumps(value,ensure_ascii=False)) for key,value in entry.items()]);database.commit();database.close()
        partial.replace(destination); destination.chmod(0o600)
        entry.update(sqliteSha256=sha(destination),bytes=destination.stat().st_size)
        save(sidecar,entry);manifest['sources'].append(entry);save(args.manifest,manifest)
        log(provider=provider,status='prepared',tableRows=entry['tableRows'],quarantinedRows=entry['quarantinedRows'],bytes=entry['bytes'])
    manifest['complete']=True;save(args.manifest,manifest)


def apply(args):
    from postgres_acceptance import APP,VAR,environment
    environment();os.environ['CACHE_URL']='';sys.path.insert(0,str(APP))
    import django;django.setup()
    from django.conf import settings
    from django.core.serializers.json import DjangoJSONEncoder
    from django.db import connection
    from django.test import override_settings
    from apps.core.models import AnalysisTask,DataSource,EvidenceRelation,KnowledgeEntity,SyncRun,ResearchDataset,MedicalCase,VisualizationArtifact
    from apps.sources.tasks import sync_source_run
    from apps.core.services.complete_evidence import digest
    assert settings.DEBUG and connection.settings_dict['NAME']=='tcm_acceptance'
    manifest=json.loads(args.manifest.read_text());assert manifest['complete'] and manifest['version']==VERSION
    backup=json.loads((args.manifest.parent/'backup.json').read_text())
    assert sha(args.manifest.parent/backup['file'])==backup['sha256']
    def row_hashes(model):
        return {row['id']:digest(json.loads(json.dumps(row,cls=DjangoJSONEncoder))) for row in model.objects.order_by('pk').values()}
    original={model._meta.label:row_hashes(model) for model in (AnalysisTask,ResearchDataset,MedicalCase,VisualizationArtifact)}
    state_path=args.manifest.parent/'apply-state.json'
    if state_path.exists():
        if not args.resume: raise ValueError('Apply journal exists; inspect and use --resume explicitly.')
        state=json.loads(state_path.read_text())
        assert not state.get('complete') and state['backupSha256']==backup['sha256']
        original={label:{int(pk):value for pk,value in rows.items()} for label,rows in state['researchBefore'].items()}
        for model in (AnalysisTask,ResearchDataset,MedicalCase,VisualizationArtifact):
            now=row_hashes(model);assert all(now.get(pk)==value for pk,value in original[model._meta.label].items())
    else:
        state={'startedAt':datetime.now(timezone.utc).isoformat(),'sources':[],'researchBefore':original,'backupSha256':backup['sha256'],'externalCalls':False}
    save(state_path,state)
    logger=logging.getLogger('apps.sources.sqlite_sync')
    logger.setLevel(logging.INFO)
    handler=logging.StreamHandler(sys.stdout);handler.setFormatter(logging.Formatter('%(asctime)s %(message)s'));logger.addHandler(handler)
    account=json.loads((VAR/'accounts.json').read_text())['admin']['id']
    names={'disease':'旧版疾病关联资料（两表）','hit':'HIT 原始知识资料','tcmsp':'TCMSP 原始知识资料',
           'batman':'BATMAN 原始知识资料','tcmip':'TCMIP 原始知识资料','herb':'HERB 原始知识资料'}
    for entry in manifest['sources']:
        provider=entry['provider'];path=Path(settings.SQLITE_SOURCE_ROOT)/entry['databaseFile']
        assert sha(path)==entry['sqliteSha256'] and entry['bytes']<=settings.SQLITE_SOURCE_MAX_BYTES
        config={'connector':'sqlite-herb-compound-target','databaseFile':path.name,'table':'herb_component_target',
                'herbColumn':'herb','compoundColumn':'component','targetColumn':'target','targetCellMode':'single','rowMetadataColumn':'extra'}
        if provider=='disease':
            config.update(diseaseTargetTable='disease_target',diseaseColumn='disease',diseaseTargetColumn='target',diseaseSourceColumn='source',
                diseaseHerbTargetTable='disease_herb_target',diseaseHerbColumn='disease',diseaseHerbHerbColumn='herb',diseaseHerbTargetColumn='target',diseaseRowMetadataColumn='extra')
        previous=next((item for item in state['sources'] if item['provider']==provider),None)
        if previous and previous['phase']=='succeeded':
            assert EvidenceRelation.objects.filter(source_release_id=previous['sourceReleaseId'],is_active=True).count()==previous['activeRelations']
            log(provider=provider,phase='already-applied');continue
        if previous:
            source=DataSource.objects.get(pk=previous['sourceId'])
            assert source.configuration==config
            if previous.get('applyRunId'):
                old=SyncRun.objects.get(pk=previous['applyRunId'])
            else:
                old=SyncRun.objects.filter(source=source,status=SyncRun.Status.RUNNING,preview_summary__mode='apply').order_by('-pk').first()
            if old and old.status==SyncRun.Status.RUNNING:
                from django.utils import timezone as django_timezone
                old.status=SyncRun.Status.FAILED;old.error_summary='本机运维导入中断，未提交事务已回滚，使用原预览重试。';old.finished_at=django_timezone.now()
                old.save(update_fields=['status','error_summary','finished_at'])
                previous.setdefault('interruptedRuns',[]).append(old.pk)
        elif provider=='hit':
            source=DataSource.objects.get(pk=5,configuration__databaseFile='hit-identity-first100.sqlite3')
            source.configuration=config;source.save(update_fields=['configuration'])
        else:
            slug='legacy-full-'+provider
            if DataSource.objects.filter(slug=slug).exists(): raise ValueError('Source already exists; inspect journal before repeating.')
            source=DataSource.objects.create(slug=slug,name=names[provider],enabled=True,access_mode=DataSource.AccessMode.MANUAL,configuration=config,
                description='用户提供的旧知识资料；原始行/来源编号断言保留，物种及权威身份未核实。')
        item=previous or {'provider':provider,'sourceId':source.pk,'phase':'preview','inputRows':sum(entry['tableRows'].values()),'quarantinedRows':entry['quarantinedRows']}
        if previous is None: state['sources'].append(item)
        save(state_path,state);started=time.perf_counter();log(provider=provider,phase='preview',sourceId=source.pk)
        with override_settings(SQLITE_SOURCE_MAX_ROWS=1_000_000):
            preview=SyncRun.objects.filter(pk=item.get('previewRunId'),source=source,status=SyncRun.Status.SUCCEEDED,preview_summary__mode='preview').first()
            if preview is None:
                preview=SyncRun.objects.create(source=source,requested_by_id=account,preview_summary={'mode':'preview','connector':config['connector']})
                result=sync_source_run(preview.pk);preview.refresh_from_db()
            else: result={'status':'succeeded'}
            item['previewRunId']=preview.pk
            if result['status']!='succeeded':
                item.update(phase='failed-preview',error=preview.error_summary);save(state_path,state);raise RuntimeError(preview.error_summary)
            item.update(phase='apply',preview=preview.preview_summary);save(state_path,state);log(provider=provider,phase='apply',rows=preview.records_seen)
            apply_run=SyncRun.objects.create(source=source,requested_by_id=account,release=preview.release,cursor=preview.cursor,
                records_seen=preview.records_seen,preview_summary={**preview.preview_summary,'mode':'apply','connector':config['connector']})
            result=sync_source_run(apply_run.pk);apply_run.refresh_from_db()
            item['applyRunId']=apply_run.pk
            if result['status']!='succeeded':
                item.update(phase='failed-apply',error=apply_run.error_summary);save(state_path,state);raise RuntimeError(apply_run.error_summary)
        source.name=names[provider];source.save(update_fields=['name'])
        entity_count=KnowledgeEntity.objects.filter(source_release__source=source,is_active=True).count()
        edge_count=EvidenceRelation.objects.filter(source_release=apply_run.release,is_active=True).count()
        assert edge_count==preview.preview_summary['relationships']
        assert apply_run.records_seen==sum(entry['tableRows'].values())
        item.update(phase='succeeded',sourceReleaseId=apply_run.release_id,activeEntities=entity_count,activeRelations=edge_count,
                    seconds=round(time.perf_counter()-started,3),originalWorkbookChecksums=[x['sha256'] for x in entry['workbooks']])
        save(state_path,state);log(provider=provider,phase='succeeded',entities=entity_count,relations=edge_count,seconds=item['seconds'])
    for model in (AnalysisTask,ResearchDataset,MedicalCase,VisualizationArtifact):
        after=row_hashes(model);assert all(after.get(pk)==value for pk,value in original[model._meta.label].items())
    state.update(completedAt=datetime.now(timezone.utc).isoformat(),researchUnchanged=True,complete=True)
    save(state_path,state);log(complete=True,sources=len(state['sources']),researchUnchanged=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest='command',required=True)
    prep=sub.add_parser('prepare');prep.add_argument('--inputs',type=Path,required=True);prep.add_argument('--output-root',type=Path,required=True);prep.add_argument('--manifest',type=Path,required=True)
    run=sub.add_parser('apply');run.add_argument('--manifest',type=Path,required=True);run.add_argument('--resume',action='store_true')
    args=parser.parse_args();prepare(args) if args.command=='prepare' else apply(args)


if __name__=='__main__':main()
