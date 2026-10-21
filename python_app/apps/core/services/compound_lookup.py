"""Resolve query keys to existing compounds without changing chemical identity.

Only explicit old-main alias entries expand a name. Punctuation is literal;
provider/reference assertions return candidates, never merge catalogue entities.
"""
import hashlib
import json
import re

from django.conf import settings
from django.db.models import Q

from apps.core.models import EntityIdentifier, KnowledgeEntity
from .component_names import ALIAS_DATA

VERSION = 'compound-lookup-1'
_CID = re.compile(r'(?:CID:)?([1-9][0-9]*)', re.IGNORECASE)
_CHEMBL = re.compile(r'CHEMBL[1-9][0-9]*')


class CompoundLookupInputError(ValueError):
    pass


def _alias_terms(query):
    """Exact declared strings only; do not reuse family/punctuation normalization."""
    terms = [query]
    profiles = []
    for profile in ALIAS_DATA['records']:
        if profile.get('fuzzy'):
            continue
        if any(query.casefold() == alias.strip().casefold() for alias in profile['aliases']):
            terms.extend(alias.strip() for alias in profile['aliases'] if alias.strip())
            profiles.append(profile['english'])
    terms = list(dict.fromkeys(terms))
    if len(terms) > 40:
        raise CompoundLookupInputError('明确别名展开超过查询保护额度，请使用来源编号。')
    return terms, profiles


def validate_compound_query(query):
    prefix, separator, value = query.partition(':')
    if not separator:
        return
    if prefix.casefold() == 'entity':
        if not re.fullmatch(r'[1-9][0-9]{0,18}', value) or int(value) > 2**63 - 1:
            raise CompoundLookupInputError('平台实体编号应为有效的正整数，例如 entity:123。')
    if prefix.casefold() in {'pubchem', 'cid'} and not re.fullmatch(r'[1-9][0-9]{0,19}', value):
        raise CompoundLookupInputError('PubChem 查询应为单个编号，例如 pubchem:167691。')
    if prefix.casefold() == 'chembl' and not _CHEMBL.fullmatch(value):
        raise CompoundLookupInputError('ChEMBL 查询应包含完整编号，例如 chembl:CHEMBL123。')


def _visible_compounds():
    return KnowledgeEntity.objects.filter(entity_type='compound', is_active=True).filter(
        Q(source_release__isnull=True) | Q(source_release__source__enabled=True)
    ).select_related('source_release__source')


def resolve_compounds(query, *, limit):
    validate_compound_query(query)
    base = _visible_compounds()
    prefix, separator, value = query.partition(':')
    prefix_key = prefix.casefold()
    resolution = {'version': VERSION, 'input': query, 'strategy': 'name', 'expandedNames': [query],
                  'identityMerged': False, 'authorityIdentityVerified': False, 'matchEvidence': [], 'warnings': []}
    evidence = {}
    if separator and prefix_key == 'entity':
        queryset = base.filter(pk=int(value));resolution['strategy'] = 'platform_entity_id'
    elif separator and prefix_key in {'pubchem', 'cid', 'chembl'}:
        namespace = 'pubchem' if prefix_key in {'pubchem', 'cid'} else 'chembl'
        resolution.update(strategy='reference_identifier', namespace=namespace, identifier=value)
        registered = list(EntityIdentifier.objects.filter(namespace=namespace, identifier=value, is_active=True,
            source_release__source__enabled=True, entity__entity_type='compound').select_related('source_release__source'))
        for item in registered:
            evidence.setdefault(item.entity_id, []).append({'method': 'registered_identifier', 'namespace': namespace,
                'identifier': value, 'sourceReleaseId': item.source_release_id, 'sourceSlug': item.source_release.source.slug,
                'sourceVersion': item.source_release.version})
        candidates = base.filter(metadata__has_key='sourceReferences').select_related(None).only('id', 'metadata')
        for item in candidates.iterator(chunk_size=250):
            references = item.metadata.get('sourceReferences', []) if isinstance(item.metadata, dict) else []
            if not isinstance(references, list):
                continue
            for reference in references:
                if not isinstance(reference, dict) or reference.get('namespace') != namespace:
                    continue
                raw = reference.get('identifier')
                if not isinstance(raw, str):
                    continue
                match = _CID.fullmatch(raw) if namespace == 'pubchem' else _CHEMBL.fullmatch(raw)
                normalized = match.group(1) if match and namespace == 'pubchem' else raw if match else None
                if normalized == value:
                    evidence.setdefault(item.pk, []).append({'method': 'source_reported_reference', 'namespace': namespace,
                        'identifier': value, 'originalIdentifier': raw, 'status': 'source_reported_unverified'})
        queryset = base.filter(pk__in=evidence)
        resolution['warnings'].append('来源声明的外部编号仅用于寻找候选，不据此确认化学身份或合并实体。')
    elif separator and prefix_key != 'sqlite' and (
        prefix_key in {key.casefold() for key in settings.COMPOUND_SOURCE_ALIASES}
        or base.filter(source_release__source__slug=prefix).exists()
    ):
        slugs = next((slugs for key, slugs in settings.COMPOUND_SOURCE_ALIASES.items() if key.casefold() == prefix_key), [prefix])
        queryset = base.filter(source_release__source__slug__in=slugs, metadata__sourceEntityId=value)
        resolution.update(strategy='source_identifier', sourceSlugs=sorted(slugs), identifier=value)
    else:
        # An exact platform stable key remains useful even without a source
        # alias configuration. It does not confer a canonical chemical ID.
        stable = base.filter(stable_id=query)
        if separator and stable.exists():
            queryset = stable;resolution['strategy'] = 'platform_stable_id'
        else:
            terms, profiles = _alias_terms(query)
            conditions = Q()
            for term in terms:
                conditions |= Q(label__iexact=term)
            queryset = base.filter(conditions)
            resolution['expandedNames'] = terms
            if profiles:
                resolution.update(strategy='explicit_main_alias', aliasProfiles=profiles,
                    aliasSource=ALIAS_DATA['source'], aliasSourceCommit=ALIAS_DATA['sourceCommit'],
                    aliasDataSha256=hashlib.sha256(json.dumps(ALIAS_DATA, sort_keys=True, ensure_ascii=False,
                        separators=(',', ':')).encode()).hexdigest())
                resolution['warnings'].append('使用旧 main 明确列出的名称映射查询；不同来源和编号仍分别保留。')
    rows = list(queryset.order_by('stable_id')[:limit + 1])
    truncated = len(rows) > limit
    rows = rows[:limit]
    for item in rows:
        proof = evidence.get(item.pk) or [{'method': ('exact_name' if item.label.casefold() == query.casefold()
                                                   else resolution['strategy'])}]
        resolution['matchEvidence'].append({'entityId': item.pk, 'stableId': item.stable_id, 'originalLabel': item.label,
            'sourceSlug': item.source_release.source.slug if item.source_release_id else None,
            'sourceReleaseId': item.source_release_id, 'sourceVersion': item.source_release.version if item.source_release_id else None,
            'sourceEntityId': item.metadata.get('sourceEntityId') if isinstance(item.metadata, dict) else None, 'basis': proof})
    if ',' in query or '，' in query:
        resolution['warnings'].append('本次逗号按原文检索；未据标点拆分、登记别名或合并成分。')
    return rows, truncated, resolution
