from django.db import models
from .knowledge import KnowledgeEntity
from .sources import SourceRelease


class TargetMaster(models.Model):
    """Species-qualified gene/protein identities, independent of source records."""
    key = models.CharField(max_length=120, primary_key=True)
    namespace = models.CharField(max_length=24, choices=[('entrez', 'NCBI Gene'), ('uniprot', 'UniProt')])
    identifier = models.CharField(max_length=64)
    taxon_key = models.CharField(max_length=32)
    label = models.CharField(max_length=300)
    symbol = models.CharField(max_length=100, blank=True)
    reference_release = models.ForeignKey(SourceRelease, on_delete=models.PROTECT)
    class Meta:
        constraints = [models.UniqueConstraint(fields=['namespace', 'identifier', 'taxon_key'], name='uniq_target_master_identity')]


class TargetIdentityMapping(models.Model):
    """Immutable resolution of one legacy record against one reference/input version."""
    entity = models.ForeignKey(KnowledgeEntity, on_delete=models.PROTECT, related_name='target_identity_mappings')
    reference_release = models.ForeignKey(SourceRelease, on_delete=models.PROTECT, related_name='target_identity_mappings')
    status = models.CharField(max_length=24, choices=[('verified', '已核验'), ('candidate', '待核验'), ('ambiguous', '有歧义'), ('conflict', '有冲突'), ('unmapped', '未映射')])
    master = models.ForeignKey(TargetMaster, on_delete=models.PROTECT, null=True, blank=True, related_name='source_mappings')
    gene = models.ForeignKey(TargetMaster, on_delete=models.PROTECT, null=True, blank=True, related_name='gene_mappings')
    match_method = models.CharField(max_length=80, blank=True)
    input_sha256 = models.CharField(max_length=64)
    evidence = models.JSONField(default=dict)
    candidates = models.JSONField(default=list)
    candidate_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['entity', 'reference_release'], name='uniq_target_resolution_version'),
            models.CheckConstraint(condition=(models.Q(status='verified', master__isnull=False) |
                (~models.Q(status='verified') & models.Q(master__isnull=True, gene__isnull=True))), name='target_verified_master_guard'),
        ]
        indexes = [models.Index(fields=['reference_release', 'status'], name='target_resolution_status_idx')]
