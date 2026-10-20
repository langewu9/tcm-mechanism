from rest_framework import serializers

from .models import ProteomicsRowResult


class ProteomicsRowResultSerializer(serializers.ModelSerializer):
    matched_entity_label = serializers.CharField(source="matched_entity.label", read_only=True)

    class Meta:
        model = ProteomicsRowResult
        fields = [
            "row_index",
            "original_label",
            "protein_name",
            "normalized_symbol",
            "external_identifiers",
            "mapping_status",
            "mapping_source",
            "matched_entity",
            "matched_entity_label",
            "log2_fold_change",
            "p_value",
            "fdr",
            "direction",
            "selected",
            "exclusion_reasons",
            "qc_warnings",
        ]
        read_only_fields = fields
