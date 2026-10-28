"""Exact observed names are search aliases, never an identity merge rule."""
import re
from django.db.models import Min, Q, Subquery, Value
from django.db.models.functions import Upper
from apps.core.models import DataSource, KnowledgeEntity, SourceEntityMapping
from .component_names import alias_for_name


def exact_entity_names(entity_type, label):
    """Expand curated exact synonyms for retrieval, never merge identities."""
    terms = [label]
    profile = alias_for_name(label) if entity_type == KnowledgeEntity.EntityType.COMPOUND else None
    if profile and not profile.get("fuzzy"):
        terms.extend(profile["aliases"])
    return list(dict.fromkeys(terms))


def _exact_names(field, terms):
    predicate = Q()
    for term in terms:
        predicate |= Q(**{field: Upper(Value(term))})
    return predicate


def exact_entity_queryset(entity_type, label):
    # SQLite's iexact uses LIKE, which cannot use the ordinary label index.
    # Keep case folding on the database side for consistent backend semantics
    # and match the expression indexes used by both exact-name lookups.
    terms = exact_entity_names(entity_type, label)
    names = _exact_names("exact_name", terms)
    if entity_type == 'compound' and re.fullmatch(r'MOL\d{6}', label.upper()):
        names |= Q(namespace='tcmsp.mol_id', source_entity_id=label.upper())
    observations = SourceEntityMapping.objects.alias(exact_name=Upper("source_label")).filter(names, entity_type=entity_type,
        status="mapped", source_release__source__enabled=True,
        source_release__published_at__isnull=False).exclude(entity=None).values("entity_id")
    return KnowledgeEntity.objects.alias(exact_name=Upper("label")).filter(entity_type=entity_type, is_active=True).filter(
        _exact_names("exact_name", terms) | Q(pk__in=Subquery(observations))
    ).filter(Q(source_release__isnull=True) | Q(source_release__source__enabled=True))


def structural_representatives(queryset, *, relation_types=None):
    """Collapse repeated structure in graph readers, not the raw evidence store.

    Workbook joins repeat herb->compound and disease->herb once per target.
    They must not consume the entire graph limit before targets can be read.
    Target/triple edges retain every evidence row and context unchanged.
    """
    structural = {"contains", "disease_herb"}
    if relation_types is not None:
        structural.intersection_update(relation_types)
        if not structural:
            return queryset
    # JSON-key negation has SQL NULL semantics when a legacy config lacks the
    # key. A non-null FK subquery safely preserves those legacy evidence rows.
    imported_sources = DataSource.objects.filter(
        configuration__connector="local-workbooks-master").values("pk")
    imported_structure = Q(relation_type__in=structural,
        source_release__source_id__in=Subquery(imported_sources))
    ids = queryset.filter(imported_structure).order_by().values(
        "subject_id", "object_id", "relation_type", "source_release_id", "evidence_type"
    ).annotate(representative=Min("pk")).values("representative")
    return queryset.filter(~imported_structure | Q(pk__in=Subquery(ids)))
