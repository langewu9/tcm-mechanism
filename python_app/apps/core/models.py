"""Compatibility exports for models split into business domains."""

from .domain.knowledge import EvidenceRelation, KnowledgeEntity
from .domain.research import AnalysisTask, MedicalCase, ResearchDataset
from .domain.sources import DataSource, SourceRelease, SyncRun

__all__ = [
    "AnalysisTask",
    "DataSource",
    "EvidenceRelation",
    "KnowledgeEntity",
    "MedicalCase",
    "ResearchDataset",
    "SourceRelease",
    "SyncRun",
]
