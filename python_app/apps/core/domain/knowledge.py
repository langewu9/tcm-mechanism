from django.db import models

from .sources import SourceRelease

class KnowledgeEntity(models.Model):
    class EntityType(models.TextChoices):
        HERB = "herb", "中药"
        FORMULA = "formula", "方剂"
        COMPOUND = "compound", "成分"
        PROTEIN = "protein", "蛋白"
        GENE = "gene", "基因"
        DISEASE = "disease", "疾病"
        PATHWAY = "pathway", "通路"

    entity_type = models.CharField(max_length=16, choices=EntityType.choices)
    stable_id = models.CharField(max_length=160)
    label = models.CharField(max_length=300)
    organism = models.CharField(max_length=120, blank=True)
    is_active = models.BooleanField(default=True)
    source_release = models.ForeignKey(
        SourceRelease,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="knowledge_entities",
    )
    synonyms = models.JSONField(default=list, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["entity_type", "label"]
        constraints = [
            models.UniqueConstraint(
                fields=["entity_type", "stable_id"], name="uniq_knowledge_entity_type_id"
            )
        ]
        indexes = [models.Index(fields=["entity_type", "label"], name="entity_type_label_idx")]

    def __str__(self) -> str:
        return f"{self.get_entity_type_display()}: {self.label} ({self.stable_id})"


class EvidenceRelation(models.Model):
    source_release = models.ForeignKey(
        SourceRelease, on_delete=models.PROTECT, related_name="evidence_relations"
    )
    source_record_id = models.CharField(max_length=240)
    subject = models.ForeignKey(
        KnowledgeEntity, on_delete=models.PROTECT, related_name="outgoing_evidence"
    )
    object = models.ForeignKey(
        KnowledgeEntity, on_delete=models.PROTECT, related_name="incoming_evidence"
    )
    relation_type = models.CharField(max_length=80)
    evidence_type = models.CharField(max_length=120)
    score = models.DecimalField(max_digits=10, decimal_places=6, null=True, blank=True)
    evidence_text = models.TextField(blank=True)
    organism = models.CharField(max_length=120, blank=True)
    is_active = models.BooleanField(default=True)
    metadata = models.JSONField(default=dict, blank=True)
    observed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["subject__label", "relation_type", "object__label"]
        constraints = [
            models.UniqueConstraint(
                fields=["source_release", "source_record_id"], name="uniq_release_source_record"
            )
        ]
        indexes = [
            models.Index(fields=["relation_type", "evidence_type"], name="evidence_relation_type_idx")
        ]

    def __str__(self) -> str:
        return f"{self.subject} —{self.relation_type}→ {self.object}"


class EntityIdentifier(models.Model):
    """A versioned external identifier attached to a canonical knowledge entity."""

    entity = models.ForeignKey(
        KnowledgeEntity, on_delete=models.PROTECT, related_name="identifiers"
    )
    source_release = models.ForeignKey(
        SourceRelease, on_delete=models.PROTECT, related_name="entity_identifiers"
    )
    namespace = models.CharField(max_length=64)
    identifier = models.CharField(max_length=160)
    is_active = models.BooleanField(default=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["namespace", "identifier"]
        constraints = [
            models.UniqueConstraint(
                fields=["namespace", "identifier", "entity"], name="uniq_entity_external_identifier"
            ),
            models.UniqueConstraint(
                fields=["namespace", "identifier"],
                condition=models.Q(namespace__in=["uniprot", "pubchem"]),
                name="uniq_global_external_identifier",
            ),
        ]
        indexes = [models.Index(fields=["entity", "namespace"], name="entity_namespace_idx")]

    def __str__(self) -> str:
        return f"{self.namespace}:{self.identifier} → {self.entity}"
