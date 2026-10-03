"""Port main's bounded Reactome catalogue search to the versioned local data."""

from django.db.models import Count, Q

from apps.core.models import EvidenceRelation, KnowledgeEntity
from .network_pharmacology import PATHWAY_TYPES


MAX_PATHWAYS = 100
SOURCE_CODE = "origin/main@078d374:src/app/api/research/route.ts#pathway"


def search_reactome_pathways(query):
    catalogue = KnowledgeEntity.objects.filter(
        entity_type=KnowledgeEntity.EntityType.PATHWAY,
        stable_id__regex=r"^R-HSA-[0-9]+$", organism="Homo sapiens", is_active=True,
        source_release__source__slug="reactome", source_release__source__enabled=True,
    )
    matched = catalogue
    if query:
        matched = matched.filter(Q(label__icontains=query) | Q(stable_id__icontains=query))
    total, matched_total = catalogue.count(), matched.count()
    pathways = list(matched.select_related("source_release__source").order_by("label", "stable_id")[:MAX_PATHWAYS])
    annotations = EvidenceRelation.objects.filter(
        object_id__in=[item.pk for item in pathways], relation_type__in=PATHWAY_TYPES,
        is_active=True, subject__is_active=True, object__is_active=True,
        subject__entity_type__in=["gene", "protein"], source_release__source__enabled=True,
    ).filter(Q(subject__source_release__isnull=True) | Q(subject__source_release__source__enabled=True))
    counts = dict(annotations.order_by().values("object_id").annotate(
        targets=Count("subject_id", distinct=True)
    ).values_list("object_id", "targets"))
    annotation_sources = {}
    for object_id, source_slug, version in annotations.order_by().values_list(
        "object_id", "source_release__source__slug", "source_release__version"
    ).distinct():
        annotation_sources.setdefault(object_id, []).append({"sourceSlug": source_slug, "sourceVersion": version})
    releases = {item.source_release_id: item.source_release for item in pathways}
    return {
        "query": query, "catalogTotal": total, "matchedTotal": matched_total,
        "truncated": matched_total > MAX_PATHWAYS, "maxItems": MAX_PATHWAYS,
        "sourceCode": SOURCE_CODE,
        "sources": [{
            "sourceSlug": release.source.slug, "sourceVersion": release.version,
            "checksumSha256": release.checksum_sha256,
        } for release in sorted(releases.values(), key=lambda release: release.pk)],
        "items": [{
            "entityId": item.pk, "stableId": item.stable_id, "name": item.label,
            "species": item.organism, "sourceVersion": item.source_release.version,
            "checksumSha256": item.source_release.checksum_sha256,
            "sourceUrl": f"https://reactome.org/content/detail/{item.stable_id}",
            "lastSyncedAt": item.updated_at.isoformat(),
            "targetAnnotations": counts.get(item.pk, 0),
            "annotationSources": sorted(annotation_sources.get(item.pk, []), key=lambda row: (row["sourceSlug"], row["sourceVersion"])),
            "enrichmentRecords": None,
        } for item in pathways],
        "warnings": ["靶点注释数是本地启用来源的去重基因/蛋白关联数；旧版全局富集记录尚未迁入，不将缺失数据计为零。"],
    }
