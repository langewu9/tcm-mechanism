from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.models import User as DefaultUser
from django.db import transaction

from .domain.accounts import ResearcherProfile
from .models import (
    AnalysisTask,
    DataSource,
    EntityIdentifier,
    EvidenceRelation,
    KnowledgeEntity,
    MedicalCase,
    MedicalCaseAuditEvent,
    MedicalCaseCandidate,
    ResearchDataset,
    SourceRelease,
    SyncRun,
    VisualizationArtifact,
)


User = get_user_model()
if User is DefaultUser:
    admin.site.unregister(User)


@admin.register(User)
class ResearcherUserAdmin(UserAdmin):
    list_display = (*UserAdmin.list_display, "researcher_email_verified")
    readonly_fields = (*UserAdmin.readonly_fields, "researcher_email_verification")

    @admin.display(description="邮箱已验证", boolean=True)
    def researcher_email_verified(self, obj):
        profile = ResearcherProfile.objects.filter(user_id=obj.pk).only("email_verified_at").first()
        return not profile or profile.email_verified_at is not None

    @admin.display(description="研究者邮箱验证时间")
    def researcher_email_verification(self, obj):
        if not obj or not obj.pk:
            return "保存账号后显示"
        profile = ResearcherProfile.objects.filter(user_id=obj.pk).first()
        if not profile:
            return "系统管理员账号无需研究者邮箱验证"
        return profile.email_verified_at or "尚未验证"

    def get_fieldsets(self, request, obj=None):
        fieldsets = list(super().get_fieldsets(request, obj))
        for index, (name, options) in enumerate(fieldsets):
            if name == "Personal info":
                fieldsets[index] = (
                    name,
                    {**options, "fields": (*options["fields"], "researcher_email_verification")},
                )
                break
        return fieldsets

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("researcher_profile")

    def save_model(self, request, obj, form, change):
        with transaction.atomic():
            profile = (
                ResearcherProfile.objects.select_for_update().filter(user_id=obj.pk).first()
                if change and obj.pk
                else None
            )
            if profile:
                previous_email = User.objects.filter(pk=obj.pk).values_list("email", flat=True).first() or ""
                email_changed = previous_email.strip().casefold() != obj.email.strip().casefold()
                if email_changed:
                    profile.email_verified_at = None
                    profile.save(update_fields=["email_verified_at", "updated_at"])
                    obj.is_active = False
                elif profile.email_verified_at is None:
                    obj.is_active = False
            super().save_model(request, obj, form, change)


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


@admin.register(EntityIdentifier)
class EntityIdentifierAdmin(admin.ModelAdmin):
    list_display = ("namespace", "identifier", "entity", "source_release", "is_active")
    list_filter = ("namespace", "is_active", "source_release__source")
    search_fields = ("identifier", "entity__label", "entity__stable_id")
    readonly_fields = tuple(field.name for field in EntityIdentifier._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(EvidenceRelation)
class EvidenceRelationAdmin(admin.ModelAdmin):
    list_display = ("subject", "relation_type", "object", "evidence_type", "score", "is_active", "source_release")
    list_filter = ("relation_type", "evidence_type", "organism", "is_active", "source_release__source")
    search_fields = ("subject__label", "object__label", "source_record_id")


@admin.register(ResearchDataset)
class ResearchDatasetAdmin(admin.ModelAdmin):
    list_display = ("name", "owner", "original_filename", "row_count", "byte_size", "created_at")
    search_fields = ("name", "owner__username", "owner__email", "content_sha256")
    readonly_fields = ("created_at", "updated_at")


@admin.register(MedicalCase)
class MedicalCaseAdmin(admin.ModelAdmin):
    list_display = ("title", "owner", "review_status", "updated_at")
    list_filter = ("review_status",)
    search_fields = ("title", "owner__username", "owner__email")
    readonly_fields = tuple(field.name for field in MedicalCase._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(MedicalCaseAuditEvent)
class MedicalCaseAuditEventAdmin(admin.ModelAdmin):
    list_display = ("case_id_snapshot", "case_title_snapshot", "owner", "actor", "action", "created_at")
    list_filter = ("action", "created_at")
    search_fields = ("case_title_snapshot", "owner__username", "actor__username")
    readonly_fields = tuple(field.name for field in MedicalCaseAuditEvent._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(MedicalCaseCandidate)
class MedicalCaseCandidateAdmin(admin.ModelAdmin):
    list_display = ("medical_case", "task", "candidate_type", "label", "match_status", "confidence", "review_status", "reviewed_by")
    list_filter = ("candidate_type", "match_status", "review_status")
    search_fields = ("medical_case__title", "label", "entity__stable_id")
    readonly_fields = tuple(field.name for field in MedicalCaseCandidate._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(VisualizationArtifact)
class VisualizationArtifactAdmin(admin.ModelAdmin):
    list_display = ("task", "chart_key", "file_format", "owner", "byte_size", "renderer_version", "created_at")
    list_filter = ("file_format", "chart_key", "created_at")
    search_fields = ("task__id", "owner__username", "content_sha256")
    readonly_fields = tuple(field.name for field in VisualizationArtifact._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(AnalysisTask)
class AnalysisTaskAdmin(admin.ModelAdmin):
    list_display = ("id", "task_type", "status", "owner", "created_by", "progress", "created_at")
    list_filter = ("task_type", "status")
    search_fields = ("owner__username", "owner__email")
    readonly_fields = ("created_at", "started_at", "finished_at")
