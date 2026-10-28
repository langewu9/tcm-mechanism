"""Compatibility exports for models split into business domains."""

from .domain.accounts import ResearcherProfile
from .domain.knowledge import CanonicalIdentifier, EntityIdentifier, EvidenceRelation, KnowledgeEntity, SourceEntityMapping
from .domain.research import AnalysisTask, MedicalCase, MedicalCaseAuditEvent, MedicalCaseCandidate, ResearchDataset, ResearchDatasetRow, VisualizationArtifact
from .domain.sources import DataSource, SourceRecord, SourceRelease, SyncRun
from .domain.target_identity import TargetIdentityMapping, TargetMaster

__all__ = [
    "AnalysisTask",
    "DataSource",
    "CanonicalIdentifier",
    "EntityIdentifier",
    "EvidenceRelation",
    "KnowledgeEntity",
    "MedicalCase",
    "MedicalCaseAuditEvent",
    "MedicalCaseCandidate",
    "ResearchDataset",
    "ResearchDatasetRow",
    "ResearcherProfile",
    "SourceRelease",
    "SourceRecord",
    "SourceEntityMapping",
    "SyncRun",
    "VisualizationArtifact",
    "TargetMaster",
    "TargetIdentityMapping",
]
