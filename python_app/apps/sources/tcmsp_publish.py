"""Restartable, reconciled publication of a validated TCMSP staging snapshot."""
from collections import defaultdict
from pathlib import Path
import hashlib
import json
import sqlite3

from django.db import transaction
from django.db.models import Exists, OuterRef
from django.utils import timezone

from apps.core.models import CanonicalIdentifier, DataSource, EvidenceRelation, KnowledgeEntity, SourceEntityMapping, SourceRecord, SourceRelease
from .master_identity import identity_key
from .tcmsp_bundle import PARSER_VERSION, PROPERTIES, clean, dumps, sha_file
from .target_identity import build_target_identities
from .workbook_import import _insert_rows


def _stage(path):
    db=sqlite3.connect(Path(path).resolve(strict=True).as_uri()+'?mode=ro',uri=True)
    try:
        db.execute('PRAGMA query_only=ON')
        meta=json.loads(db.execute("SELECT value FROM meta WHERE key='bundle'").fetchone()[0])
        if meta['parserVersion']!=PARSER_VERSION:raise ValueError('Unsupported TCMSP stage version.')
        for key,sql in [('rawRows','SELECT count(*) FROM raw'),('relations','SELECT count(*) FROM edge')]:
            if meta['counts'][key]!=db.execute(sql).fetchone()[0]:raise ValueError('Staging count reconciliation failed.')
        if db.execute("SELECT count(*) FROM edge e JOIN raw r ON r.id=e.raw_id WHERE r.status!='accepted'").fetchone()[0]:
            raise ValueError('Quarantined row cannot support an active relationship.')
        return db,meta
    except Exception:
        db.close()
        raise


def publish_bundle(stage_path,directory,reference_manifest,*,apply=False,progress=print):
    db,meta=_stage(stage_path);directory=Path(directory).resolve(strict=True)
    try:
        for name,info in meta['files'].items():
            if sha_file(directory/name)!=info['sha256']:raise ValueError('Source workbook differs from the staged snapshot.')
        version=f'{PARSER_VERSION}:{meta["fingerprint"]}'
        if not apply:return {'state':'preview','version':version,**meta['counts']}
        source=DataSource.objects.get(slug='tcmsp')
        release,created=SourceRelease.objects.get_or_create(source=source,version=version,defaults={
            'checksum_sha256':meta['fingerprint'],'metadata':{'importState':'staging','parserVersion':PARSER_VERSION,
                'filename':'TCMSP enriched bundle','files':meta['files'],'reference':meta['reference'],
                'targetIdentityPolicy':'unique_reviewed_human_v1','internalUseOnly':True}})
        if release.metadata.get('importState')=='published':return {'state':'unchanged','releaseId':release.pk,'version':version,**release.metadata['counts']}
        if release.checksum_sha256!=meta['fingerprint']:raise ValueError('Immutable TCMSP snapshot mismatch.')

        registry={(a,b,c,d,e):pk for a,b,c,d,e,pk in CanonicalIdentifier.objects.filter(scope=source.slug).values_list('entity_type','namespace','identifier','taxon_key','scope','entity_id')}
        entity_ids={};entities=[];bindings=[];pending=[]
        reviews={r[0]:r[1:] for r in db.execute('SELECT token,entry,gene,status,reason,raw_id FROM review')}
        for token,kind,ns,identifier,label,taxon in db.execute('SELECT * FROM entity ORDER BY rowid'):
            key,_=identity_key(entity_type=kind,namespace=ns,identifier=identifier,taxon_key=taxon,source=source)
            tuple_key=tuple(key[k] for k in ['entity_type','namespace','identifier','taxon_key','scope'])
            if tuple_key in registry:entity_ids[token]=registry[tuple_key];continue
            stable='master:'+hashlib.sha256(json.dumps(key,sort_keys=True).encode()).hexdigest()[:48]
            review=reviews.get(token)
            entities.append(KnowledgeEntity(entity_type=kind,stable_id=stable,label=label,taxon_key=taxon,is_active=False,
                source_release=release,organism='Homo sapiens' if taxon=='9606' else '',
                metadata={'source':'tcmsp','sourceIdentifier':identifier,'sourceNamespace':ns,
                    'symbol':review[1] if review and review[2]=='verified' else '',
                    'speciesVerification':'validated_supplemental_uniprot' if taxon=='9606' else 'not_supplied'}))
            pending.append((token,key))
        with transaction.atomic():
            KnowledgeEntity.objects.bulk_create(entities,batch_size=500)
            for entity,(token,key) in zip(entities,pending):
                entity_ids[token]=entity.pk
                bindings.append(CanonicalIdentifier(entity=entity,**key,source=source,match_method='source_scoped'))
            CanonicalIdentifier.objects.bulk_create(bindings,batch_size=500)
        progress(f'TCMSP identities bound: {len(entity_ids):,}')

        checkpoint=int(release.metadata.get('lastRawRowid',0));batch=[];last=checkpoint
        def raw_flush():
            nonlocal batch
            with transaction.atomic():
                _insert_rows(SourceRecord,['source_release','source_record_id','payload_sha256','payload','status','created_at'],batch)
                release.metadata={**release.metadata,'lastRawRowid':last};release.save(update_fields=['metadata'])
            batch=[]
        for rowid,record,payload,status in db.execute('SELECT rowid,id,payload,status FROM raw WHERE rowid>? ORDER BY rowid',(checkpoint,)):
            batch.append((release.pk,record,hashlib.sha256(payload.encode()).hexdigest(),json.loads(payload),status,timezone.now()));last=rowid
            if len(batch)==5000:raw_flush();progress(f'TCMSP raw rows stored: {last:,}/{meta["counts"]["rawRows"]:,}')
        if batch:raw_flush()
        raw_ids=dict(SourceRecord.objects.filter(source_release=release).values_list('source_record_id','pk').iterator(chunk_size=5000))
        if len(raw_ids)!=meta['counts']['rawRows']:raise ValueError('Raw TCMSP count mismatch.')
        stable_ids={}
        ordered=list(set(entity_ids.values()))
        for i in range(0,len(ordered),500):stable_ids.update(KnowledgeEntity.objects.filter(pk__in=ordered[i:i+500]).values_list('pk','stable_id'))

        if not release.metadata.get('mappingsImported'):
            property_rows={mol:(token,raw,json.loads(values),json.loads(conflicts)) for mol,token,raw,values,conflicts in db.execute('SELECT * FROM molecule')}
            property_origins=defaultdict(dict)
            for raw,payload,mol in db.execute("SELECT id,payload,mol FROM raw WHERE kind='ingredients' AND status='accepted'"):
                if mol not in property_rows:continue
                values=json.loads(payload)['values'];props=property_rows[mol][2]
                for field,value in zip(PROPERTIES,values[6:16]):
                    if field in property_origins[mol] or props.get(field) is None:continue
                    try:matches=float(value)==props[field]
                    except (TypeError,ValueError):matches=False
                    if matches:property_origins[mol][field]=raw
            mapping_rows=[]
            for token,kind,ns,identifier,label,taxon in db.execute('SELECT * FROM entity'):
                attrs={};record=None
                if ns=='tcmsp.mol_id' and identifier in property_rows:
                    _,record,props,conflicts=property_rows[identifier]
                    attrs={'properties':props,'propertyConflicts':conflicts,'propertyRecords':property_origins[identifier]}
                if ns=='tcmsp.target_id':
                    entry,gene,status,reason,record=reviews[token]
                    attrs={'uniprot':entry,'geneSymbol':gene,'identityVerified':status=='verified',
                        'reviewStatus':status,'reviewReason':reason,'referenceSha256':meta['reference']['sha256']}
                mapping_rows.append(SourceEntityMapping(source_release=release,entity_id=entity_ids[token],entity_type=kind,
                    namespace=ns,source_entity_id=identifier,source_label=label,taxon_key=taxon,status='mapped',
                    source_record_id=raw_ids.get(record),match_method='validated_supplemental_identifier' if attrs.get('identityVerified') else 'source_scoped',metadata=attrs))
            aliases=defaultdict(lambda:{'ids':set(),'labels':set()})
            for token,ns,identifier,label in db.execute('SELECT * FROM name'):
                kind=json.loads(token)[0];item=aliases[(kind,ns,identifier)]
                item['ids'].add(entity_ids[token]);item['labels'].add(label)
            for (kind,ns,identifier),item in aliases.items():
                ids=sorted(item['ids']);entity=ids[0] if len(ids)==1 else None
                mapping_rows.append(SourceEntityMapping(source_release=release,entity_id=entity,entity_type=kind,namespace=ns,
                    source_entity_id=identifier,source_label=sorted(item['labels'])[0],taxon_key='unknown',
                    status='mapped' if entity else 'ambiguous',match_method='explicit_source_name_observation',
                    metadata={'candidateEntityPks':ids,'observedLabels':sorted(item['labels'])}))
            with transaction.atomic():
                SourceEntityMapping.objects.bulk_create(mapping_rows,batch_size=500)
                release.metadata={**release.metadata,'mappingsImported':True};release.save(update_fields=['metadata'])

        checkpoint=int(release.metadata.get('lastEdgeRowid',0));batch=[];last=checkpoint
        def edge_flush():
            nonlocal batch
            with transaction.atomic():
                _insert_rows(EvidenceRelation,['source_release','source_record_id','source_record_ref','subject','object','relation_type','evidence_type','score','evidence_text','organism','is_active','metadata','observed_at','created_at'],batch)
                release.metadata={**release.metadata,'lastEdgeRowid':last};release.save(update_fields=['metadata'])
            batch=[]
        for rowid,subject,obj,relation,evidence,context,record,metadata,n in db.execute('SELECT rowid,* FROM edge WHERE rowid>? ORDER BY rowid',(checkpoint,)):
            metadata=json.loads(metadata);metadata['sourceObservationCount']=n
            herb=metadata.pop('herbToken',None)
            if herb:metadata.update(herbStableId=stable_ids[entity_ids[herb]],diseaseStableId=stable_ids[entity_ids[subject]])
            batch.append((release.pk,f'edge:{rowid:010d}',raw_ids[record],entity_ids[subject],entity_ids[obj],relation,evidence,
                None,'','',False,metadata,None,timezone.now()));last=rowid
            if len(batch)==5000:edge_flush();progress(f'TCMSP unique edges stored: {last:,}/{meta["counts"]["relations"]:,}')
        if batch:edge_flush()
        actual=EvidenceRelation.objects.filter(source_release=release).count()
        if actual!=meta['counts']['relations']:raise ValueError('TCMSP relationship reconciliation failed.')
        counts={'rows':meta['counts']['rawRows'],'relations':actual,'accepted':meta['counts']['acceptedRows'],'quarantined':meta['counts']['quarantinedRows']}
        quality={**meta['counts'],'policy':'Only uniquely reviewed-human verified TCMSP target relationships are active; unverified rows retained for review.'}
        with transaction.atomic():
            DataSource.objects.select_for_update().get(pk=source.pk)
            EvidenceRelation.objects.filter(source_release__source=source).exclude(source_release=release).update(is_active=False)
            active_tokens={r[0] for r in db.execute('SELECT subject FROM edge UNION SELECT object FROM edge')}
            active_ids=[entity_ids[t] for t in active_tokens]
            for i in range(0,len(active_ids),500):KnowledgeEntity.objects.filter(pk__in=active_ids[i:i+500]).update(is_active=True)
            EvidenceRelation.objects.filter(source_release=release).update(is_active=True)
            old=KnowledgeEntity.objects.filter(source_release__source=source,is_active=True).annotate(
                has_out=Exists(EvidenceRelation.objects.filter(subject_id=OuterRef('pk'),is_active=True)),
                has_in=Exists(EvidenceRelation.objects.filter(object_id=OuterRef('pk'),is_active=True))).filter(has_out=False,has_in=False)
            old.update(is_active=False)
            release.published_at=timezone.now();release.metadata={**release.metadata,'importState':'published','counts':counts,'qualitySummary':quality}
            release.save(update_fields=['metadata','published_at'])
            source.configuration={**source.configuration,'activeSupplementReleaseId':release.pk};source.last_success_at=release.published_at
            source.save(update_fields=['configuration','last_success_at'])
            identity=build_target_identities(reference_manifest,apply=True)
        return {'state':'published','version':version,'releaseId':release.pk,'counts':counts,'quality':quality,'targetIdentity':identity}
    finally:db.close()
