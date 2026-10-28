"""Versioned source-local BATMAN name observations; never merge entities."""
from collections import defaultdict
from pathlib import Path
import hashlib
import json

from django.db import transaction
from django.utils import timezone
from openpyxl import load_workbook

from apps.core.models import DataSource, KnowledgeEntity, SourceEntityMapping, SourceRecord, SourceRelease
from .tcmsp_bundle import sha_file


def import_batman_names(path, *, apply=False):
    path = Path(path)
    checksum = sha_file(path)
    source = DataSource.objects.get(slug='batman')
    labels = defaultdict(set)
    for pk, label in KnowledgeEntity.objects.filter(source_release__source=source, entity_type='herb', is_active=True).values_list('pk', 'label'):
        labels[label.strip().casefold()].add(pk)
    rows = []
    aliases = defaultdict(lambda: {'ids': set(), 'names': set(), 'unknown': False, 'records': []})
    counts = {'rows': 0, 'accepted': 0, 'quarantined': 0}
    workbook = load_workbook(path, read_only=True, data_only=False)
    try:
        sheet = workbook.active
        sheet.reset_dimensions()
        values = iter(sheet.values)
        if list(next(values)) != ['Pinyin.Name', 'Chinese.Name', 'English.Name', 'Latin.Name']:
            raise ValueError('Unexpected BATMAN name headers.')
        for number, values in enumerate(values, 2):
            values = list(values)
            if not any(v is not None and str(v).strip() for v in values):
                continue
            cells = [str(v or '').strip() for v in (values + [None] * 4)[:4]]
            unsafe = len(values) > 4 or any(v.startswith('=') for v in cells)
            ids = labels[cells[1].casefold()] if cells[1] and not unsafe else set()
            status = 'accepted' if len(ids) == 1 else 'quarantined'
            record = f'Sheet1:{number}'
            payload = {'file': path.name, 'sheet': sheet.title, 'row': number, 'values': values,
                       'reason': '' if status == 'accepted' else 'unresolved_source_herb_name'}
            rows.append((record, payload, status))
            counts['rows'] += 1
            counts[status] += 1
            if unsafe:
                continue
            for kind, name in zip(['pinyin', 'chinese', 'english', 'latin'], cells):
                if not name:
                    continue
                item = aliases[(kind, name.casefold())]
                item['names'].add(name)
                item['ids'].update(ids)
                item['unknown'] |= len(ids) != 1
                item['records'].append(record)
    finally:
        workbook.close()
    if sha_file(path) != checksum:
        raise ValueError('BATMAN name workbook changed while reading.')
    counts['mappedAliases'] = sum(len(a['ids']) == 1 and not a['unknown'] for a in aliases.values())
    counts['ambiguousAliases'] = sum(len(a['ids']) > 1 or (bool(a['ids']) and a['unknown']) for a in aliases.values())
    version = 'batman-names-v1:' + checksum
    if not apply:
        return {'state': 'preview', 'version': version, **counts}
    with transaction.atomic():
        release, created = SourceRelease.objects.get_or_create(source=source, version=version, defaults={
            'checksum_sha256': checksum, 'metadata': {'filename': path.name, 'importState': 'staging', 'internalUseOnly': True}})
        if not created:
            if release.metadata.get('importState') != 'published':
                raise ValueError('Unexpected incomplete BATMAN alias snapshot.')
            return {'state': 'unchanged', 'releaseId': release.pk, 'version': version, **release.metadata['counts']}
        raw = [SourceRecord(source_release=release, source_record_id=key, payload=payload, status=status,
                            payload_sha256=hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest())
               for key, payload, status in rows]
        SourceRecord.objects.bulk_create(raw, batch_size=500)
        raw_ids = {row.source_record_id: row.pk for row in raw}
        mappings = []
        for (kind, normalized), item in aliases.items():
            ids = sorted(item['ids'])
            mapped = len(ids) == 1 and not item['unknown']
            mappings.append(SourceEntityMapping(source_release=release, source_record_id=raw_ids[item['records'][0]],
                entity_id=ids[0] if mapped else None, entity_type='herb', namespace=f'batman.name.{kind}',
                source_entity_id=hashlib.sha256(normalized.encode()).hexdigest(), source_label=sorted(item['names'])[0][:300],
                taxon_key='unknown', status='mapped' if mapped else 'ambiguous' if ids else 'unmapped',
                match_method='explicit_source_name_observation', metadata={'candidateEntityPks': ids,
                    'observedLabels': sorted(item['names']), 'sourceRecords': item['records'], 'retrievalOnly': True}))
        SourceEntityMapping.objects.bulk_create(mappings, batch_size=500)
        release.metadata = {**release.metadata, 'importState': 'published', 'counts': counts,
                            'policy': 'Source-local retrieval aliases only; no entity or target identity merging.'}
        release.published_at = timezone.now()
        release.save(update_fields=['metadata', 'published_at'])
    return {'state': 'published', 'releaseId': release.pk, 'version': version, **counts}
