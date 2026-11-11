"""Apply the existing herb row support rule before a target query is sliced."""
from django.db.models import BooleanField, Case, Exists, F, Func, OuterRef, Q, Value, When

from .herb_row_support import _legacy_row


class _IntegerSourceRow(Func):
    """Match the Python rule ``type(sourceRowId) is int`` on supported DBs.

    JSON equality alone equates 2 and 2.0 on PostgreSQL/SQLite. A numeric-looking
    string or boolean must not consume the cap either. All SQL fragments below
    are static; the metadata expression is compiled by Django.
    """
    output_field = BooleanField()

    def as_sqlite(self, compiler, connection, **extra_context):
        expression, params = compiler.compile(self.source_expressions[0])
        return f"(JSON_TYPE({expression}, '$.sourceRowId') = 'integer')", params

    def as_postgresql(self, compiler, connection, **extra_context):
        expression, params = compiler.compile(self.source_expressions[0])
        return (f"(jsonb_typeof({expression} -> 'sourceRowId') = 'number' "
                f"AND ({expression} ->> 'sourceRowId') ~ '^-?[0-9]+$')", params * 2)


def supported_target_queryset(queryset, herb_relations=None, *, herb_queryset=None):
    """Keep generic compound annotations or a selected legacy original row.

    Selected herb edge IDs bound the correlated EXISTS to the already-read
    scope. EXISTS cannot multiply target rows when several herbs support one
    annotation. The caller retains its original visibility checks and cap.
    """
    if herb_queryset is not None:
        compounds = herb_queryset.order_by().values("object_id")
        row_support = herb_queryset.alias(
            _integer_source_row=_IntegerSourceRow(F("metadata")),
        ).filter(_integer_source_row=True)
    else:
        herb_relations = list(herb_relations)
        compounds = {relation.object_id for relation in herb_relations}
        if not compounds:
            return queryset.none()
        selected_ids = [relation.pk for relation in herb_relations if _legacy_row(relation)[1] is not None]
        row_support = queryset.model.objects.filter(pk__in=selected_ids)
    queryset = queryset.filter(subject_id__in=compounds).alias(
        _legacy_triple=Case(
            When(source_release__metadata__connector="sqlite-herb-compound-target", then=Value(True)),
            default=Value(False), output_field=BooleanField(),
        ),
    )
    row_support = row_support.filter(
        object_id=OuterRef("subject_id"),
        source_release_id=OuterRef("source_release_id"),
        metadata__sourceRowId=OuterRef("metadata__sourceRowId"),
    )
    return queryset.alias(
        _integer_source_row=_IntegerSourceRow(F("metadata")),
        _selected_herb_row=Exists(row_support),
    ).filter(Q(_legacy_triple=False) | Q(_integer_source_row=True, _selected_herb_row=True))
