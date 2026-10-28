from django.db.models import Count
from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.response import Response
from rest_framework.views import APIView
from apps.core.models import CanonicalIdentifier, EvidenceRelation, KnowledgeEntity, SourceEntityMapping, SourceRecord, SourceRelease
from apps.sources.views import IsPlatformAdministrator
from apps.sources.target_identity_views import target_identity_summary

class MasterSummarySerializer(serializers.Serializer):
    schemaVersion = serializers.CharField()
    entityCount = serializers.IntegerField()
    canonicalIdCount = serializers.IntegerField()
    identifierCount = serializers.IntegerField()
    mappingCount = serializers.IntegerField()
    rawRecordCount = serializers.IntegerField()
    relationCount = serializers.IntegerField()
    publishedRelationCount = serializers.IntegerField()
    quarantinedRecordCount = serializers.IntegerField()
    workbookReleases = serializers.ListField(child=serializers.JSONField())
    entityTypes = serializers.DictField(child=serializers.IntegerField())
    mappingStatuses = serializers.DictField(child=serializers.IntegerField())
    compatibility = serializers.JSONField()
    targetIdentity = serializers.JSONField()

class MasterTableSummaryView(APIView):
    permission_classes = [IsPlatformAdministrator]
    @extend_schema(responses=MasterSummarySerializer)
    def get(self, request):
        return Response({'schemaVersion': 'master-identity-v1',
            'targetIdentity': target_identity_summary(),
            'entityCount': KnowledgeEntity.objects.count(), 'canonicalIdCount': KnowledgeEntity.objects.exclude(canonical_id=None).count(),
            'identifierCount': CanonicalIdentifier.objects.count(), 'mappingCount': SourceEntityMapping.objects.count(),
            'rawRecordCount': SourceRecord.objects.count(), 'relationCount': EvidenceRelation.objects.count(),
            'publishedRelationCount': EvidenceRelation.objects.filter(is_active=True).count(),
            'quarantinedRecordCount': SourceRecord.objects.filter(status='quarantined').count(),
            'workbookReleases': [{'source': r.source.slug, 'version': r.version,
                'active': not r.source.configuration.get('activeSupplementReleaseId') or r.source.configuration['activeSupplementReleaseId'] == r.pk,
                'qualitySummary': r.metadata.get('qualitySummary', {}),
                'state': r.metadata.get('importState', 'unknown'), 'counts': r.metadata.get('counts', {}),
                'internalUseOnly': True} for r in SourceRelease.objects.filter(
                    source__configuration__connector='local-workbooks-master').select_related('source').order_by('source__slug', '-created_at')],
            'entityTypes': dict(KnowledgeEntity.objects.order_by().values('entity_type').annotate(n=Count('id')).values_list('entity_type', 'n')),
            'mappingStatuses': dict(SourceEntityMapping.objects.order_by().values('status').annotate(n=Count('id')).values_list('status', 'n')),
            'compatibility': {'legacyIntegerPkPreserved': True, 'legacyStableIdsPreserved': True,
                'namesNeverAutoMerged': True, 'speciesIsolated': True, 'snapshotVersionsPreserved': True}})
