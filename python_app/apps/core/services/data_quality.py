from apps.core.models import DataSource,SourceRelease,SourceEntityMapping


def current_tcmsp_release():
    source=DataSource.objects.filter(slug='tcmsp',enabled=True).first()
    pk=source.configuration.get('activeSupplementReleaseId') if source else None
    return SourceRelease.objects.filter(pk=pk,source=source,metadata__importState='published').first() if pk else None


def data_quality_notices():
    release=current_tcmsp_release()
    if not release:return []
    quality=release.metadata.get('qualitySummary',{})
    return [{'source':'tcmsp','version':release.version,'quarantinedRows':quality.get('quarantinedRows',0),
        'verifiedTargetIds':quality.get('targetReviewStatuses',{}).get('verified',0),
        'message':'TCMSP当前版本仅激活编号与名称核验一致的人类靶点关系；未核验来源行保留待复核。源表验证标记与预测关系分别保存。'}]


def compound_properties(entity):
    if entity.entity_type!='compound':return None
    release=current_tcmsp_release()
    if not release:return None
    row=SourceEntityMapping.objects.filter(entity=entity,source_release=release,namespace='tcmsp.mol_id',status='mapped').select_related('source_record').first()
    if not row or not row.metadata.get('properties'):return None
    return {'source':'tcmsp','sourceVersion':release.version,'sourceCompoundId':row.source_entity_id,
        'values':row.metadata['properties'],'conflicts':row.metadata.get('propertyConflicts',[]),
        'fieldSourceRecords':row.metadata.get('propertyRecords',{}),
        'sourceRecordId':row.source_record.source_record_id if row.source_record else None,
        'note':'空值表示缺失或存在冲突；OB、DL及通透性等为来源属性，不是临床疗效或统计显著性。'}
