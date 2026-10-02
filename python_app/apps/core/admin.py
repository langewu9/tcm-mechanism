from django.contrib import admin

from .models import (
    AnalysisTask,
    DataSource,
    EvidenceRelation,
    KnowledgeEntity,
    MedicalCase,
    ResearchDataset,
    SourceRelease,
    SyncRun,
)


@admin.register(DataSource)
class DataSourceAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "access_mode", "enabled", "last_success_at")
    list_filter = ("access_mode", "enabled")
    search_fields = ("name", "slug")
    readonly_fields = ("created_at", "updated_at")


@admin.register(SourceRelease)
class SourceReleaseAdmin(admin.ModelAdmin):
    list_display = ("source", "version", "published_at", "created_at")
    list_filter = ("source",)
    search_fields = ("source__name", "version", "checksum_sha256")


@admin.register(SyncRun)
class SyncRunAdmin(admin.ModelAdmin):
    list_display = ("source", "status", "trigger", "requested_by", "records_seen", "created_at", "finished_at")
    list_filter = ("status", "trigger", "source")
    readonly_fields = ("created_at", "started_at", "finished_at", "preview_summary", "cursor")


@admin.register(KnowledgeEntity)
class KnowledgeEntityAdmin(admin.ModelAdmin):
    list_display = ("label", "entity_type", "stable_id", "organism", "is_active", "updated_at")
    list_filter = ("entity_type", "organism", "is_active")
    search_fields = ("label", "stable_id")


@admin.register(EvidenceRelation)
class EvidenceRelationAdmin(admin.ModelAdmin):
    list_display = ("subject", "relation_type", "object", "evidence_type", "score", "source_release")
    list_filter = ("relation_type", "evidence_type", "organism", "source_release__source")
    search_fields = ("subject__label", "object__label", "source_record_id")


@admin.register(ResearchDataset)
class ResearchDatasetAdmin(admin.ModelAdmin):
    list_display = ("name", "owner", "original_filename", "byte_size", "created_at")
    search_fields = ("name", "owner__username", "owner__email", "content_sha256")
    readonly_fields = ("created_at", "updated_at")


@admin.register(MedicalCase)
class MedicalCaseAdmin(admin.ModelAdmin):
    list_display = ("title", "owner", "review_status", "updated_at")
    list_filter = ("review_status",)
    search_fields = ("title", "owner__username", "owner__email")
    readonly_fields = ("created_at", "updated_at")


@admin.register(AnalysisTask)
class AnalysisTaskAdmin(admin.ModelAdmin):
    list_display = ("id", "task_type", "status", "owner", "created_by", "progress", "created_at")
    list_filter = ("task_type", "status")
    search_fields = ("owner__username", "owner__email")
    readonly_fields = ("created_at", "started_at", "finished_at")
