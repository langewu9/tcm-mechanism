from django.db.models import Count, Q
from rest_framework.response import Response
from rest_framework.views import APIView
from apps.core.models import TargetIdentityMapping, TargetMaster
from apps.sources.target_identity import current_release
from apps.sources.views import IsPlatformAdministrator


def target_identity_summary():
    release = current_release()
    if not release: return {'available': False}
    qs = TargetIdentityMapping.objects.filter(reference_release=release)
    sources = {}
    for row in qs.values('entity__source_release__source__slug', 'status').annotate(n=Count('id')):
        source = row['entity__source_release__source__slug'] or 'global'
        sources.setdefault(source, {})[row['status']] = row['n']
    return {'available': True, 'releaseId': release.pk, 'version': release.version,
        'referenceSha256': release.checksum_sha256, 'masterCount': TargetMaster.objects.count(),
        'statuses': dict(qs.order_by().values('status').annotate(n=Count('id')).values_list('status','n')),
        'sourceStatuses': sources, 'reference': release.metadata.get('reference', {}),
        'comparisonUnit': 'Gene and protein identities are compared separately; species is part of every key.'}


class TargetIdentityListView(APIView):
    permission_classes = [IsPlatformAdministrator]
    def get(self, request):
        release = current_release()
        if not release: return Response({'count': 0, 'results': [], 'available': False})
        qs = TargetIdentityMapping.objects.filter(reference_release=release).select_related('entity__source_release__source', 'master', 'gene').order_by('entity_id')
        status = request.query_params.get('status', '')
        if status:
            if status not in {'verified','candidate','ambiguous','conflict','unmapped'}: return Response({'error':'无效映射状态。'}, status=400)
            qs = qs.filter(status=status)
        query = request.query_params.get('search', '').strip()[:120]
        if query:
            qs = qs.filter(Q(entity__label__icontains=query) | Q(master__identifier__iexact=query) | Q(gene__identifier__iexact=query))
        try: page = max(1, int(request.query_params.get('page', '1')))
        except ValueError: return Response({'error':'页码必须为整数。'}, status=400)
        count = qs.count()
        return Response({'available': True, 'referenceVersion': release.version, 'count': count, 'page': page,
            'results': [{'entityId': row.entity_id, 'label': row.entity.label, 'originalTaxon': row.entity.taxon_key,
                'source': row.entity.source_release.source.slug if row.entity.source_release_id else 'global',
                'status': row.status, 'method': row.match_method, 'masterKey': row.master_id,
                'geneKey': row.gene_id, 'candidateCount': row.candidate_count, 'candidates': row.candidates,
                'evidence': row.evidence} for row in qs[(page-1)*50:page*50]]})
