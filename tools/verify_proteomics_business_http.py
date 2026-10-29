"""Local upload/queue/QC/export/R proof using labelled synthetic measurements.

Retains two datasets, three successful analyses, one expected failed analysis,
and two R renders. A journal prevents duplicate creation when explicitly resumed.
No experiment, model request, external mapping or catalogue mutation is implied.
"""
import argparse
import csv
import hashlib
import io
import json
import math
from pathlib import Path
import sys

from audit_proteomics_business import JOB, THRESHOLDS, write_json
from audit_network_business import canonical, digest
from postgres_acceptance import APP, VAR, environment
from smoke_local_workspace import LocalClient, wait_task


def main():
    parser = argparse.ArgumentParser(description=__doc__);parser.add_argument('--resume', action='store_true');args = parser.parse_args()
    output, journal = JOB/'http-verified.json', JOB/'http-state.json'
    if output.exists():
        raise ValueError('Completed proof exists; do not create duplicate research records.')
    audit = json.loads((JOB/'local-audit.json').read_text());assert audit['passed'] and audit['syntheticMeasurements']
    environment();sys.path.insert(0,str(APP))
    import django
    django.setup()
    from django.core.serializers.json import DjangoJSONEncoder
    from django.core.files.storage import default_storage
    from django.db.models import Max
    from openpyxl import load_workbook
    from apps.core.models import AnalysisTask,ResearchDataset,ResearchDatasetRow,MedicalCase,VisualizationArtifact,DataSource,SourceRelease,KnowledgeEntity,EvidenceRelation,EntityIdentifier
    from apps.proteomics.models import ProteomicsRowResult
    from apps.core.services.visualization import build_chart_payload
    def row_hashes(model):
        return {str(row['id']):digest(json.loads(json.dumps(row,cls=DjangoJSONEncoder))) for row in model.objects.order_by('pk').values()}
    def catalogue():
        checksum=hashlib.sha256();count=0
        for row in KnowledgeEntity.objects.order_by('pk').values().iterator(chunk_size=500):
            checksum.update((json.dumps(row,cls=DjangoJSONEncoder,ensure_ascii=False,sort_keys=True,separators=(',',':'))+'\n').encode());count+=1
        return {'entities':count,'entityContentSha256':checksum.hexdigest(),'relations':EvidenceRelation.objects.count(),
            'maxRelationId':EvidenceRelation.objects.aggregate(value=Max('pk'))['value'],'registeredIdentifiers':EntityIdentifier.objects.count()}
    models=(AnalysisTask,ResearchDataset,ResearchDatasetRow,ProteomicsRowResult,MedicalCase,VisualizationArtifact,DataSource,SourceRelease)
    if journal.exists():
        if not args.resume:raise ValueError('Inspect the journal and explicitly --resume.')
        state=json.loads(journal.read_text())
    else:state={'before':{model._meta.label:row_hashes(model) for model in models},'catalogueBefore':catalogue(),'datasets':{},'tasks':{},'renders':{}}
    def save_state():
        tmp=journal.with_suffix('.partial');write_json(tmp,state);tmp.replace(journal)
    save_state()
    accounts=json.loads((VAR/'accounts.json').read_text())
    owner=LocalClient(accounts['a'],base_url='http://127.0.0.1:5174',csrf_cookie_name='tcm_pg_csrf')
    other=LocalClient(accounts['b'],base_url='http://127.0.0.1:5174',csrf_cookie_name='tcm_pg_csrf')
    for key,filename in [('differential',audit['differential']['file']),('matrix',audit['matrixCases'][0]['file'])]:
        content=(JOB/filename).read_bytes()
        if key not in state['datasets']:
            boundary='ProteomicsSyntheticBusinessAcceptance'
            body=(f'--{boundary}\r\nContent-Disposition: form-data; name="name"\r\n\r\n蛋白组学合成业务核验-{key}（非实验数据）\r\n'
                f'--{boundary}\r\nContent-Disposition: form-data; name="description"\r\n\r\nSYNTHETIC: column, QC, local mapping and queue acceptance only; not measured experiments.\r\n'
                f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\nContent-Type: text/csv\r\n\r\n').encode()+content+f'\r\n--{boundary}--\r\n'.encode()
            _,dataset=owner.request('/api/v1/research/datasets/',method='POST',raw=body,content_type=f'multipart/form-data; boundary={boundary}',expected=201)
            state['datasets'][key]=dataset['id'];save_state()
        _,dataset=owner.request(f'/api/v1/research/datasets/{state["datasets"][key]}/')
        assert dataset['content_sha256']==hashlib.sha256(content).hexdigest()
        _,downloaded=owner.request(f'/api/v1/research/datasets/{dataset["id"]}/download/');assert downloaded==content
        if key=='differential':
            assert dataset['columns'][-3:]==['Sample','Sample_3','Sample_2'] and dataset['row_count']==15
            for row in ResearchDatasetRow.objects.filter(dataset_id=dataset['id']).values_list('data',flat=True):
                assert [row[k] for k in dataset['columns'][-3:]]==['KEEP1','KEEP2','KEEP3']
        other.request(f'/api/v1/research/datasets/{dataset["id"]}/download/',expected=404)
    report={'syntheticMeasurements':True,'externalCalls':False,'tasks':[],'renders':[]}
    common={'thresholds':THRESHOLDS,'referenceTargets':[],'externalReactome':False,'externalString':False,'externalGProfiler':False}
    plans=[('matrix-'+case['design']['designType'],'matrix',{**common,'analysisMode':'raw_matrix','matrixDesign':case['design']}) for case in audit['matrixCases']]
    plans += [('ambiguous-columns','differential',{**common,'mapping':{}}),
        ('differential','differential',{**common,'mapping':audit['differential']['mapping']})]
    differential=None
    for name,dataset_key,parameters in plans:
        if name not in state['tasks']:
            _,queued=owner.request(f'/api/v1/research/datasets/{state["datasets"][dataset_key]}/analyze/',method='POST',expected=202,
                data={**parameters,'name':f'SYNTHETIC business proof {name} (not an experiment)'})
            state['tasks'][name]=queued['id'];save_state()
        task_id=state['tasks'][name];base=f'/api/v1/research/analysis-tasks/{task_id}'
        if name=='ambiguous-columns':
            import time
            for _ in range(120):
                _,task=owner.request(base+'/')
                if task['status']=='failed':break
                assert task['status'] in {'queued','running'};time.sleep(.5)
            assert task['status']=='failed' and '对应多列' in task['error_summary'] and not task['result']
            assert not ProteomicsRowResult.objects.filter(task_id=task_id).exists()
            report['tasks'].append({'id':task_id,'name':name,'expectedFailure':True,'partialResultNotPublished':True});continue
        task=wait_task(owner,task_id);result=task['result']
        assert result['algorithmVersion']=='proteomics-py-1.10'
        rows=[];page=1
        while True:
            _,response=owner.request(base+f'/rows/?page={page}&page_size=5');rows.extend(response['results'])
            if not response['next']:break
            page+=1
        assert [row['row_index'] for row in rows]==list(range(len(rows)))
        if name=='differential':
            differential=task;expected=audit['differential']
            assert result['qc']==expected['qc'] and result['summary']==expected['summary']
            assert result['mapping']==expected['mapping']
            for actual,wanted in zip(rows,expected['rows'],strict=True):
                for field,value in wanted.items():assert actual['matched_entity' if field=='matched_entity_id' else field]==value,(field,actual,value)
            assert [row['row_index'] for row in rows if row['selected']]==expected['expectedSelectedIndices']
        else:
            expected=next(case for case in audit['matrixCases'] if name=='matrix-'+case['design']['designType'])
            assert [row['row_index'] for row in rows if row['selected']]==expected['expectedSelectedIndices']
            assert result['qc']['rawMatrix']==expected['qc']
            for reference in expected['reference']:
                actual=rows[int(reference['row_index'])]
                for field,refkey in [('log2_fold_change','effect'),('p_value','p_value'),('fdr','fdr')]:
                    assert math.isclose(actual[field],float(reference[refkey]),rel_tol=1e-9,abs_tol=1e-12)
        for selected,count in [('true',sum(row['selected'] for row in rows)),('false',sum(not row['selected'] for row in rows))]:
            _,page_data=owner.request(base+f'/rows/?selected={selected}&page_size=5');assert page_data['count']==count
        for extension in ['csv','xlsx','pdf']:
            _,content=owner.request(base+f'/export/?file_format={extension}')
            path=JOB/f'task-{task_id}.{extension}';path.write_bytes(content);path.chmod(0o600)
            if extension=='csv':
                exported=list(csv.DictReader(io.StringIO(content.decode('utf-8-sig'))));assert len(exported)==len(rows)
                assert [row['原始标识'] for row in exported]==[row['original_label'] for row in rows]
                assert [row['通过筛选'] for row in exported]==['通过' if row['selected'] else '排除' for row in rows]
                assert [row['质量警告'] for row in exported]==['; '.join(row['qc_warnings']) for row in rows]
            elif extension=='xlsx':
                book=load_workbook(io.BytesIO(content),read_only=True,data_only=True)
                values=list(book['逐行结果'].iter_rows(values_only=True));assert len(values)==len(rows)+1
                assert [row[1] or '' for row in values[1:]]==[row['original_label'] for row in rows]
                assert [row[11] for row in values[1:]]==['通过' if row['selected'] else '排除' for row in rows];book.close()
            else:assert content.startswith(b'%PDF')
        _,restored=owner.request(base+'/');assert restored['result']==result and restored['input_parameters']==task['input_parameters']
        for suffix in ['/','/rows/','/export/?file_format=csv']:other.request(base+suffix,expected=404)
        report['tasks'].append({'id':task_id,'name':name,'rows':len(rows),'qc':result['qc'],'summary':result['summary'],
            'allRowsAndExportsMatch':True,'getRecoveryUnchanged':True,'otherOwnerDenied':True})
        print(json.dumps({'id':task_id,'name':name,'rows':len(rows),'selected':result['summary']['selectedRowCount']},ensure_ascii=False),flush=True)
    assert differential
    parent=AnalysisTask.objects.get(pk=differential['id'])
    for key in ['proteomics_summary','proteomics_volcano']:
        payload=build_chart_payload(parent,key)
        if key=='proteomics_volcano':
            assert len(payload['data'])==11 and sum(row['selected'] for row in payload['data'])==8
        if key not in state['renders']:
            _,queued=owner.request(f'/api/v1/research/analysis-tasks/{parent.pk}/visualizations/',method='POST',expected=202,data={'chartKey':key})
            state['renders'][key]=queued['id'];save_state()
        rendered=wait_task(owner,state['renders'][key]);assert rendered['parent_task']==parent.pk and rendered['result']['inputSha256']==payload['inputSha256']
        artifacts=rendered['result']['artifacts'];assert {row['format'] for row in artifacts}=={'svg','pdf','png','html'}
        for artifact in artifacts:
            _,content=owner.request(artifact['downloadUrl']);assert hashlib.sha256(content).hexdigest()==artifact['sha256'];other.request(artifact['downloadUrl'],expected=404)
        png=VisualizationArtifact.objects.get(render_task_id=rendered['id'],file_format='png')
        report['renders'].append({'id':rendered['id'],'parentTask':parent.pk,'chartKey':key,'inputSha256':payload['inputSha256'],
            'pngPath':default_storage.path(png.storage_key),'formats':['svg','pdf','png','html'],'artifactHashesMatch':True,'otherOwnerDenied':True})
    for model in models:
        after=row_hashes(model);assert all(after.get(pk)==value for pk,value in state['before'][model._meta.label].items()),model._meta.label
    assert catalogue()==state['catalogueBefore']
    report.update(passed=True,oldResearchUnchanged=True,catalogueUnchanged=True,previousTasks=len(state['before']['core.AnalysisTask']))
    write_json(output,report);state['complete']=True;save_state()
    print(json.dumps({'passed':True,'datasets':state['datasets'],'tasks':state['tasks'],'renders':state['renders'],'previousRecordsUnchanged':True},ensure_ascii=False))


if __name__=='__main__':main()
