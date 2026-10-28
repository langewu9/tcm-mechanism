"""Stage/validate TCMSP exports before publishing a complete source version.

Raw rows are immutable. Only uniquely name/ID-verified reviewed human target
relationships are published; prediction scores are never treated as P/FDR.
"""
from collections import Counter, defaultdict
from pathlib import Path
import hashlib
import json
import math
import re
import sqlite3

from openpyxl import load_workbook

from .connectors.target_reference import ACCESSION, load_reference
from .target_identity import ReferenceIndex, name_key

PARSER_VERSION = 'tcmsp-rich-v1'
TARGET_HEADER = ['来源中药pinyin','来源中药','MOL_ID','molecule_ID','molecule_name','target_name','target_ID','drugbank_ID','validated','SVM_score','RF_score','Entry','GENE name']
INGREDIENT_HEADER = ['来源中药pinyin','来源中药pinyin','MOL_ID','molecule_ID','file_ID','molecule_name','ob','mw','alogp','caco2','bbb','halflife','hdon','hacc','dl','FASA']
DISEASE_HEADER = ['target_name','target_ID','drugbank_ID','disease_name','disease_ID']
PROPERTIES = ['ob','mw','alogp','caco2','bbb','halflife','hdon','hacc','dl','FASA']
MOL_ID = re.compile(r'MOL[0-9]{6}')


def dumps(value): return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
def sha_file(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
    return h.hexdigest()
def clean(value):
    if value is None: return ''
    if isinstance(value,float) and value.is_integer(): return str(int(value))
    return str(value).strip()
def json_value(v):
    if isinstance(v,float) and not math.isfinite(v): return str(v)
    return v if isinstance(v,(str,int,float,bool)) or v is None else str(v)
def trim(row):
    row=list(row)
    while row and row[-1] is None:row.pop()
    return row


def sheet_rows(path, expected, sheet=0):
    book=load_workbook(path,read_only=True,data_only=False,keep_links=False)
    try:
        ws=book.worksheets[sheet];ws.reset_dimensions()
        rows=ws.iter_rows(values_only=True)
        header=[clean(v) for v in trim(next(rows,()))]
        if header!=expected: raise ValueError(f'{path.name}: unexpected header {header!r}')
        for number,row in enumerate(rows,2):
            row=trim(row)
            if not any(clean(v) for v in row):continue
            values=[json_value(v) for v in row]
            issue=''
            if len(row)>len(header):issue='unexpected_extra_columns'
            if any(isinstance(v,str) and v.startswith('=') for v in row):issue='formula_in_data'
            yield number,values+[None]*max(0,len(header)-len(values)),issue,ws.title
    finally:book.close()


class BundleStage:
    def __init__(self,path):
        self.path=Path(path);self.path.parent.mkdir(parents=True,exist_ok=True)
        self.db=sqlite3.connect(path)
        self.db.executescript('''
        CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT);
        CREATE TABLE raw(id TEXT PRIMARY KEY,kind TEXT,target_id TEXT,herb TEXT,mol TEXT,payload TEXT,status TEXT,reason TEXT);
        CREATE INDEX raw_target_idx ON raw(kind,target_id);
        CREATE TABLE entity(token TEXT PRIMARY KEY,kind TEXT,namespace TEXT,identifier TEXT,label TEXT,taxon TEXT);
        CREATE TABLE name(token TEXT,namespace TEXT,identifier TEXT,label TEXT,UNIQUE(token,namespace,identifier,label));
        CREATE TABLE edge(subject TEXT,object TEXT,relation TEXT,evidence TEXT,context TEXT,raw_id TEXT,metadata TEXT,observations INTEGER DEFAULT 1,
          UNIQUE(subject,object,relation,evidence,context));
        CREATE TABLE molecule(id TEXT PRIMARY KEY,token TEXT,raw_id TEXT,properties TEXT,conflicts TEXT);
        CREATE TABLE review(id TEXT PRIMARY KEY,token TEXT,entry TEXT,gene TEXT,status TEXT,reason TEXT,raw_id TEXT);
        ''')
    def entity(self,kind,namespace,identifier,label,taxon='unknown'):
        if not clean(identifier) or len(clean(identifier))>300 or not clean(label): raise ValueError('Missing/oversized source entity identifier.')
        identifier=clean(identifier)
        if namespace.endswith('_name'):identifier=name_key(identifier)
        token=dumps([kind,namespace,identifier,taxon])
        self.db.execute('INSERT OR IGNORE INTO entity VALUES(?,?,?,?,?,?)',(token,kind,namespace,identifier,clean(label)[:300],taxon))
        return token
    def name(self,token,namespace,identifier,label):
        identifier=clean(identifier)
        if len(identifier)>300:identifier='sha256:'+hashlib.sha256(identifier.encode()).hexdigest()
        if identifier and clean(label):self.db.execute('INSERT OR IGNORE INTO name VALUES(?,?,?,?)',(token,namespace,identifier,clean(label)[:300]))
    def raw(self,record_id,kind,file,sheet,number,values,*,target='',herb='',mol='',status='accepted',reason=''):
        payload=dumps({'file':file,'sheet':sheet,'row':number,'values':values})
        self.db.execute('INSERT INTO raw VALUES(?,?,?,?,?,?,?,?)',(record_id,kind,target,herb,mol,payload,status,reason))
    def edge(self,subject,obj,relation,evidence,raw_id,metadata=None,context=''):
        self.db.execute('''INSERT INTO edge(subject,object,relation,evidence,context,raw_id,metadata)
          VALUES(?,?,?,?,?,?,?) ON CONFLICT(subject,object,relation,evidence,context)
          DO UPDATE SET observations=observations+1''',(subject,obj,relation,evidence,context,raw_id,dumps(metadata or {})))


def _review(group,index):
    if len(group['names'])!=1 or len(group['entries'])!=1 or len(group['genes'])>1:return 'conflict','source_target_has_conflicting_annotations'
    entry=next(iter(group['entries']));label=next(iter(group['names']))
    if not ACCESSION.fullmatch(entry):return 'unmapped','missing_or_invalid_uniprot'
    if entry not in index.proteins:return 'outside_scope','outside_reviewed_human_reference'
    candidates=index.names['protein'].get(name_key(label),set())
    key=f'uniprot:9606:{entry}'
    if key not in candidates:return 'conflict','target_name_identifier_mismatch'
    if candidates!={key}:return 'ambiguous','non_unique_protein_name'
    provided=next(iter(group['genes']),'')
    symbols={name_key(v) for v in index.proteins[entry]['symbol'].split(';') if clean(v)}
    if provided and name_key(provided) not in symbols:return 'conflict','provided_gene_disagrees'
    return 'verified','exact_source_id_and_unique_reviewed_human_name'


def prepare_bundle(directory,manifest_path,stage_path,progress=print):
    directory=Path(directory).resolve(strict=True);stage_path=Path(stage_path)
    if stage_path.exists():raise ValueError('Choose a new staging path; an existing stage is never overwritten.')
    manifest,reference=load_reference(manifest_path);index=ReferenceIndex(reference)
    ingredient=directory/'TCMSP全部数据/TCMSP_merged_ingredients.xlsx'
    targets=directory/'TCMSP全部数据/TCMSP_merged_targets.xlsx'
    disease_dir=directory/'TCMSP_data'
    files=[ingredient,targets,*sorted(disease_dir.glob('*_disease.xlsx'))]
    if len(files)<3:raise ValueError('Missing TCMSP ingredient/target/disease files.')
    file_info={str(p.relative_to(directory)):{'sha256':sha_file(p),'bytes':p.stat().st_size} for p in files}
    stage=BundleStage(stage_path);db=stage.db;herbs=defaultdict(set);reviews=defaultdict(lambda:{'names':set(),'entries':set(),'genes':set(),'first':''})
    molecules={};stats=Counter();disease_names=defaultdict(set)
    def plant(pinyin,chinese):
        if not clean(chinese):raise ValueError('Missing source herb name.')
        token=stage.entity('herb','tcmsp.herb_name',chinese,chinese)
        herbs[name_key(pinyin)].add((clean(chinese),token));stage.name(token,'tcmsp.herb_pinyin',pinyin,pinyin)
        return token
    def molecule(mol,label):
        mol=clean(mol).upper()
        if not MOL_ID.fullmatch(mol):raise ValueError('Invalid TCMSP MOL_ID.')
        token=stage.entity('compound','tcmsp.mol_id',mol,label)
        stage.name(token,'tcmsp.compound_name',label,label);molecules[mol]=token
        return token
    try:
        for number,row,issue,sheet in sheet_rows(ingredient,INGREDIENT_HEADER):
            stats['ingredientRows']+=1
            record=f'ingredients:{number:09d}'
            if clean(row[1]):plant(row[0],row[1])
            if not clean(row[1]) or not MOL_ID.fullmatch(clean(row[2]).upper()) or not clean(row[5]):
                stage.raw(record,'ingredients',str(ingredient.relative_to(directory)),sheet,number,row,status='quarantined',reason='missing_or_invalid_compound_identity');continue
            herb=plant(row[0],row[1]);mol=molecule(row[2],row[5]);props={};invalid=[]
            for field,value in zip(PROPERTIES,row[6:16]):
                if value is None or clean(value)=='':props[field]=None;continue
                try:parsed=float(value)
                except (TypeError,ValueError):parsed=float('nan')
                if not math.isfinite(parsed) or (field=='mw' and parsed<=0) or (field=='ob' and not 0<=parsed<=100):
                    props[field]=None;invalid.append(field)
                else:props[field]=parsed
            stage.raw(record,'ingredients',str(ingredient.relative_to(directory)),sheet,number,row,herb=clean(row[1]),mol=clean(row[2]),status='quarantined' if issue else 'accepted',reason=issue)
            if not issue:stage.edge(herb,mol,'contains','database_assertion',record)
            old=db.execute('SELECT properties,conflicts FROM molecule WHERE id=?',(clean(row[2]),)).fetchone()
            conflicts=set(invalid)
            if old:
                prior=json.loads(old[0]);conflicts.update(json.loads(old[1]))
                for field in PROPERTIES:
                    if prior.get(field) is not None and props.get(field) is not None and not math.isclose(prior[field],props[field],rel_tol=1e-12,abs_tol=1e-12):conflicts.add(field)
                    if prior.get(field) is None and field not in conflicts:prior[field]=props[field]
                props=prior
            for field in conflicts:props[field]=None
            db.execute('INSERT INTO molecule VALUES(?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET properties=excluded.properties,conflicts=excluded.conflicts',(clean(row[2]),mol,record,dumps(props),dumps(sorted(conflicts))))
        db.commit();progress(f'Ingredients staged: {stats["ingredientRows"]:,}')
        for number,row,issue,sheet in sheet_rows(targets,TARGET_HEADER):
            stats['targetRows']+=1
            record=f'targets:{number:09d}';target=clean(row[6])
            if not clean(row[1]) or not MOL_ID.fullmatch(clean(row[2]).upper()) or not clean(row[4]) or not target or not clean(row[5]):
                stage.raw(record,'targets',str(targets.relative_to(directory)),sheet,number,row,target=target,status='quarantined',reason='missing_source_relationship_identity');continue
            herb=plant(row[0],row[1]);mol=molecule(row[2],row[4])
            if not target:issue=issue or 'missing_target_id'
            group=reviews[target];group['names'].add(clean(row[5]));group['entries'].add(clean(row[11]));group['genes'].add(clean(row[12]));group['first']=group['first'] or record
            stage.raw(record,'targets',str(targets.relative_to(directory)),sheet,number,row,target=target,herb=clean(row[1]),mol=clean(row[2]),status='quarantined',reason=issue or 'awaiting_target_review')
            if stats['targetRows']%50000==0:db.commit();progress(f'Target rows staged: {stats["targetRows"]:,}')
        for target,group in reviews.items():
            status,reason=_review(group,index);entry=next(iter(sorted(group['entries'])),'');label=next(iter(sorted(group['names'])),'')
            token=stage.entity('protein','tcmsp.target_id',target,label,'9606' if status=='verified' else 'unknown')
            raw_id=group['first']
            db.execute('INSERT INTO review VALUES(?,?,?,?,?,?,?)',(target,token,entry,next(iter(sorted(group['genes'])),''),status,reason,raw_id))
            db.execute("UPDATE raw SET status=?,reason=? WHERE kind='targets' AND target_id=? AND reason='awaiting_target_review'",('accepted' if status=='verified' else 'quarantined',reason,target))
        db.commit()
        review_rows={r[0]:r[1:] for r in db.execute('SELECT id,token,entry,gene,status,reason,raw_id FROM review')}
        for record,payload in db.execute("SELECT id,payload FROM raw WHERE kind='targets' AND status='accepted'"):
            row=json.loads(payload)['values'];herb=plant(row[0],row[1]);mol=molecules[clean(row[2])];target=review_rows[clean(row[6])][0]
            validated=clean(row[8])=='validated';scores={};score_issue=False
            for key,value in zip(('svmScore','rfScore'),row[9:11]):
                if value is None or clean(value)=='':scores[key]=None;continue
                try:value=float(value)
                except (TypeError,ValueError):value=float('nan')
                if not math.isfinite(value) or not 0<=value<=1:score_issue=True;scores[key]=None
                else:scores[key]=value
            if score_issue:
                db.execute("UPDATE raw SET status='quarantined',reason='invalid_prediction_score' WHERE id=?",(record,));continue
            stage.edge(herb,mol,'contains','database_assertion',record)
            metadata={'sourceTargetId':clean(row[6]),'molId':clean(row[2]),'sourceValidated':validated,**scores,'scoreMeaning':'source_predictor_scores_not_p_or_fdr'}
            stage.edge(mol,target,'targets','source_validated_assertion' if validated else 'predicted_target',record,metadata,context=dumps(scores))
        for file_no,path in enumerate(files[2:],1):
            pinyin=path.name[:-len('_disease.xlsx')];mapped=herbs.get(name_key(pinyin),set())
            herb_name,herb=next(iter(mapped)) if len(mapped)==1 else ('','')
            for number,row,issue,sheet in sheet_rows(path,DISEASE_HEADER):
                target_id=clean(row[1]);disease_id=clean(row[4]);review=review_rows.get(target_id)
                record=f'disease:{pinyin}:{number:09d}'
                if not herb:issue=issue or 'unresolved_herb_file'
                if not disease_id or not clean(row[3]):issue=issue or 'missing_disease_identity'
                if not review or review[3]!='verified':issue=issue or 'target_not_verified'
                elif name_key(clean(row[0]))!=name_key(next(iter(reviews[target_id]['names']))):issue=issue or 'target_id_name_conflict'
                stage.raw(record,'disease',str(path.relative_to(directory)),sheet,number,row,target=target_id,herb=herb_name,status='quarantined' if issue else 'accepted',reason=issue)
                stats['diseaseRows']+=1
                if issue:continue
                disease=stage.entity('disease','tcmsp.disease_id',disease_id,row[3]);disease_names[disease].add(name_key(row[3]))
                stage.name(disease,'tcmsp.disease_name',row[3],row[3])
                metadata={'context':'disease_herb_target_triple','herbToken':herb,'sourceTargetId':target_id,'sourceDiseaseId':disease_id}
                stage.edge(disease,herb,'disease_herb','database_assertion',record)
                stage.edge(disease,review[0],'disease_herb_target','database_assertion',record,metadata,context=herb)
            db.commit()
            if file_no%50==0:progress(f'Disease files staged: {file_no}/{len(files)-2}; {stats["diseaseRows"]:,} rows')
        for token,names in disease_names.items():
            if len(names)>1:
                raw_ids=[r[0] for r in db.execute('SELECT DISTINCT raw_id FROM edge WHERE subject=?',(token,))]
                db.executemany("UPDATE raw SET status='quarantined',reason='disease_id_name_conflict' WHERE id=?",[(r,) for r in raw_ids])
                db.execute('DELETE FROM edge WHERE subject=?',(token,));stats['conflictingDiseaseIds']+=1
        for name,info in file_info.items():
            if sha_file(directory/name)!=info['sha256']:raise ValueError('Input workbook changed during staging.')
        summary={**stats,'rawRows':db.execute('SELECT count(*) FROM raw').fetchone()[0],
            'acceptedRows':db.execute("SELECT count(*) FROM raw WHERE status='accepted'").fetchone()[0],
            'quarantinedRows':db.execute("SELECT count(*) FROM raw WHERE status='quarantined'").fetchone()[0],
            'relations':db.execute('SELECT count(*) FROM edge').fetchone()[0],
            'targetReviewStatuses':dict(db.execute('SELECT status,count(*) FROM review GROUP BY status')),
            'quarantineReasons':dict(db.execute("SELECT reason,count(*) FROM raw WHERE status='quarantined' GROUP BY reason")),
            'evidenceTypes':dict(db.execute('SELECT evidence,count(*) FROM edge GROUP BY evidence')),
            'moleculesWithProperties':db.execute('SELECT count(*) FROM molecule').fetchone()[0],
            'propertyConflictMolecules':db.execute("SELECT count(*) FROM molecule WHERE conflicts!='[]'").fetchone()[0]}
        envelope={'parserVersion':PARSER_VERSION,'files':file_info,'reference':manifest,'counts':summary}
        envelope['fingerprint']=hashlib.sha256(dumps(envelope).encode()).hexdigest()
        db.execute('INSERT INTO meta VALUES(?,?)',('bundle',dumps(envelope)));db.commit()
        if db.execute('PRAGMA quick_check').fetchone()[0]!='ok':raise ValueError('Staging integrity failed.')
        return envelope
    finally:db.close()
