import uuid
from django.db import models
from django.db.models.functions import Upper

from .sources import DataSource, SourceRecord, SourceRelease

class KnowledgeEntity(models.Model):
    class EntityType(models.TextChoices):
        SYNDROME = "syndrome", "证候"
        HERB = "herb", "中药"
        FORMULA = "formula", "方剂"
        COMPOUND = "compound", "成分"
        PROTEIN = "protein", "蛋白"
        GENE = "gene", "基因"
        DISEASE = "disease", "疾病"
        PATHWAY = "pathway", "通路"

    entity_type = models.CharField(max_length=16, choices=EntityType.choices)
    stable_id = models.CharField(max_length=160)
    # Existing integer PK and stable_id remain compatible with saved tasks/UI.
    canonical_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    taxon_key = models.CharField(max_length=32, default="unknown")
    identity_status = models.CharField(max_length=24, default="source_scoped", choices=[
        ("source_scoped", "来源范围标识"), ("identifier_bound", "已按强标识关联"),
    ])
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
        indexes = [
            models.Index(fields=["entity_type", "label"], name="entity_type_label_idx"),
            models.Index(Upper("label"), models.F("entity_type"), name="entity_exact_name_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.get_entity_type_display()}: {self.label} ({self.stable_id})"


class EvidenceRelation(models.Model):
    source_release = models.ForeignKey(
        SourceRelease, on_delete=models.PROTECT, related_name="evidence_relations"
    )
    source_record_id = models.CharField(max_length=240)
    source_record_ref = models.ForeignKey(SourceRecord, on_delete=models.PROTECT, null=True, blank=True, related_name="relations")
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
            models.Index(fields=["relation_type", "evidence_type"], name="evidence_relation_type_idx"),
            models.Index(fields=["subject", "relation_type"], name="evidence_subject_type_idx"),
            models.Index(fields=["object", "relation_type"], name="evidence_object_type_idx"),
            models.Index(fields=["subject", "relation_type", "is_active", "object", "source_release"], name="evidence_subject_cover_idx"),
            models.Index(fields=["object", "relation_type", "is_active", "subject", "source_release"], name="evidence_object_cover_idx"),
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
                condition=models.Q(namespace__in=["uniprot", "pubchem", "string"]),
                name="uniq_global_external_identifier",
            ),
        ]
        indexes = [models.Index(fields=["entity", "namespace"], name="entity_namespace_idx")]

    def __str__(self) -> str:
        return f"{self.namespace}:{self.identifier} → {self.entity}"


class CanonicalIdentifier(models.Model):
    """Authoritative identity binding; version observations stay separate."""
    entity = models.ForeignKey(KnowledgeEntity, on_delete=models.PROTECT, related_name="master_identifiers")
    entity_type = models.CharField(max_length=16, choices=KnowledgeEntity.EntityType.choices)
    namespace = models.CharField(max_length=64)
    identifier = models.CharField(max_length=300)
    taxon_key = models.CharField(max_length=32, default="unknown")
    scope = models.CharField(max_length=80, blank=True, default="")
    source = models.ForeignKey(DataSource, on_delete=models.PROTECT, null=True, blank=True, related_name="master_identifiers")
    match_method = models.CharField(max_length=40)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["entity_type", "namespace", "identifier", "taxon_key", "scope"], name="uniq_master_identifier")]
        indexes = [models.Index(fields=["namespace", "identifier"], name="master_namespace_id_idx")]


class SourceEntityMapping(models.Model):
    """One source-version observation, including unmerged/ambiguous records."""
    source_release = models.ForeignKey(SourceRelease, on_delete=models.PROTECT, related_name="master_mappings")
    source_record = models.ForeignKey(SourceRecord, on_delete=models.PROTECT, null=True, blank=True, related_name="mappings")
    source_entity_id = models.CharField(max_length=300)
    source_label = models.CharField(max_length=300, blank=True)
    entity_type = models.CharField(max_length=16, choices=KnowledgeEntity.EntityType.choices)
    namespace = models.CharField(max_length=64)
    taxon_key = models.CharField(max_length=32, default="unknown")
    entity = models.ForeignKey(KnowledgeEntity, on_delete=models.PROTECT, null=True, blank=True, related_name="source_mappings")
    status = models.CharField(max_length=24, choices=[("mapped", "已映射"), ("unmapped", "未映射"), ("ambiguous", "有歧义"), ("conflict", "标识冲突")])
    match_method = models.CharField(max_length=40, blank=True)
    reason = models.TextField(blank=True)
    metadata = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["source_release", "entity_type", "namespace", "source_entity_id", "taxon_key"], name="uniq_source_master_mapping")]
        indexes = [
            models.Index(fields=["status", "source_release"], name="master_mapping_status_idx"),
            models.Index(Upper("source_label"), models.F("entity_type"), models.F("status"), name="mapping_exact_name_idx"),
        ]
