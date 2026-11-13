from django.db.models import Count, Q
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
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
    for row in qs.values('entity__source_release__source__slug', 'entity__metadata', 'status'):
        source = row['entity__source_release__source__slug'] or (row['entity__metadata'] or {}).get('source') or 'global'
        source_statuses = sources.setdefault(source, {})
        source_statuses[row['status']] = source_statuses.get(row['status'], 0) + 1
    taxa_by_source = {}
    for row in qs.values('entity__source_release__source__slug', 'entity__metadata', 'master__taxon_key', 'evidence'):
        source = row['entity__source_release__source__slug'] or (row['entity__metadata'] or {}).get('source') or 'global'
        evidence = row['evidence'] or {}
        public_match = evidence.get('matchedPublicReference') or {}
        taxon = row['master__taxon_key'] or public_match.get('taxon') or evidence.get('resolvedTaxon') or evidence.get('resolutionTaxon') or evidence.get('originalTaxon') or 'unknown'
        source_taxa = taxa_by_source.setdefault(source, {})
        source_taxa[taxon] = source_taxa.get(taxon, 0) + 1
    mapped_master_count = qs.exclude(master=None).values('master_id').distinct().count()
    standard_master_count = release.metadata.get('standardTargets')
    if not isinstance(standard_master_count, int):
        standard_master_count = TargetMaster.objects.count()
    return {'available': True, 'releaseId': release.pk, 'version': release.version,
        'referenceSha256': release.checksum_sha256,
        'masterCount': standard_master_count, 'mappedMasterCount': mapped_master_count,
        'statuses': dict(qs.order_by().values('status').annotate(n=Count('id')).values_list('status','n')),
        'sourceStatuses': sources, 'reference': release.metadata.get('reference', {}),
        'referenceCatalogs': release.metadata.get('referenceCatalogs', {}),
        'sourceSpeciesAssertions': release.metadata.get('sourceSpeciesAssertions', {}),
        'publicTaxa': release.metadata.get('publicTaxa', {}), 'taxaBySource': taxa_by_source,
        'comparisonUnit': 'Gene and protein identities are compared separately; species is part of every key.'}


class TargetIdentityListView(APIView):
    permission_classes = [IsPlatformAdministrator]
    @extend_schema(operation_id="target_identity_list", responses=OpenApiTypes.OBJECT, parameters=[
        OpenApiParameter("status", str, enum=["verified", "candidate", "ambiguous", "conflict", "unmapped"]),
        OpenApiParameter("search", str), OpenApiParameter("page", int),
    ])
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
                'masterIdentifier': row.master.identifier if row.master_id else None,
                'masterLabel': row.master.label if row.master_id else None,
                'resolvedTaxon': row.master.taxon_key if row.master_id else ((row.evidence or {}).get('matchedPublicReference') or {}).get('taxon') or (row.evidence or {}).get('resolvedTaxon') or (row.evidence or {}).get('resolutionTaxon'),
                'resolvedOrganism': ((row.evidence or {}).get('matchedPublicReference') or {}).get('organism') or
                    ((row.evidence or {}).get('taxonEvidence') or {}).get('organism', ''),
                'geneKey': row.gene_id, 'candidateCount': row.candidate_count, 'candidates': row.candidates,
                'evidence': row.evidence} for row in qs[(page-1)*50:page*50]]})
