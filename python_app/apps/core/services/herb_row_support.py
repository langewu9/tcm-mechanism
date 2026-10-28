"""Join legacy herb/compound/target triples without inventing source rows.

Generic graph annotations can support any herb containing their compound.
SQLite triples describe one original row and must join within that release/row.
"""
from collections import defaultdict


def _legacy_row(relation):
    metadata = relation.source_release.metadata
    is_legacy = (isinstance(metadata, dict) and metadata.get("connector") == "sqlite-herb-compound-target")
    if not is_legacy:
        return False, None
    metadata = relation.metadata if isinstance(relation.metadata, dict) else {}
    row_id = metadata.get("sourceRowId")
    return True, (relation.source_release_id, row_id) if type(row_id) is int else None


class HerbRowSupport:
    def __init__(self, herb_relations):
        self.by_compound = defaultdict(list)
        self.by_row = defaultdict(list)
        for relation in herb_relations:
            self.by_compound[relation.object_id].append(relation)
            is_legacy, row = _legacy_row(relation)
            if is_legacy and row is not None:
                self.by_row[(relation.object_id, row)].append(relation)

    def for_target(self, target_relation):
        is_legacy, row = _legacy_row(target_relation)
        if is_legacy:
            return self.by_row.get((target_relation.subject_id, row), []) if row is not None else []
        return self.by_compound.get(target_relation.subject_id, [])
