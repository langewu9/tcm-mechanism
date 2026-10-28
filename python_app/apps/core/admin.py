from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.models import User as DefaultUser
from django.db import transaction

from .domain.accounts import ResearcherProfile
from .forms import ResearcherUserChangeForm, ResearcherUserCreationForm
from .services.access_audit import SensitiveAdminAuditMixin
from .services.upload_quota import upload_quota_usage
from config.api_errors import request_id_for
from .models import (
    AnalysisTask,
    CanonicalIdentifier,
    DataSource,
    EntityIdentifier,
    EvidenceRelation,
    KnowledgeEntity,
    MedicalCase,
    MedicalCaseAuditEvent,
    MedicalCaseCandidate,
    ResearchDataset,
    ResearchDatasetAuditEvent,
    SourceRelease,
    SourceRecord,
    SourceEntityMapping,
    SyncRun,
    VisualizationArtifact,
    TargetMaster,
    TargetIdentityMapping,
    SensitiveAccessEvent,
    ResearchUploadQuota,
)


User = get_user_model()
if User is DefaultUser:
    admin.site.unregister(User)


class ResearchUploadQuotaInline(admin.StackedInline):
    model = ResearchUploadQuota
    fk_name = "user"
    extra = 1
    max_num = 1
    can_delete = False
    fields = ("storage_limit_mib", "dataset_limit", "updated_by", "updated_at")
    readonly_fields = ("updated_by", "updated_at")


@admin.register(User)
class ResearcherUserAdmin(SensitiveAdminAuditMixin, UserAdmin):
    form = ResearcherUserChangeForm
    add_form = ResearcherUserCreationForm
    list_display = (*UserAdmin.list_display, "researcher_email_verified")
    readonly_fields = (*UserAdmin.readonly_fields, "researcher_email_verification", "researcher_upload_usage")
    inlines = (ResearchUploadQuotaInline,)

    @admin.display(description="当前上传占用和有效额度")
    def researcher_upload_usage(self, obj):
        if not obj or not obj.pk:
            return "保存用户后显示。"
        usage = upload_quota_usage(obj.pk)
        return (
            f"容量 {usage['usedBytes'] / (1024 ** 2):.2f} / {usage['limitBytes'] / (1024 ** 2):.2f} MiB；"
            f"数据集 {usage['usedDatasets']} / {usage['limitDatasets']}。归档文件仍计入占用。"
        )

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
        if obj and obj.pk:
            fieldsets.append(("研究资料上传额度", {"fields": ("researcher_upload_usage",)}))
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

    def save_formset(self, request, form, formset, change):
        if formset.model is not ResearchUploadQuota:
            return super().save_formset(request, form, formset, change)
        for quota in formset.save(commit=False):
            previous = ResearchUploadQuota.objects.filter(user_id=quota.user_id).first()
            before = {
                "storageLimitMiB": previous.storage_limit_mib if previous else None,
                "datasetLimit": previous.dataset_limit if previous else None,
            }
            quota.updated_by = request.user
            quota.save()
            SensitiveAccessEvent.objects.create(
                actor=request.user, operation="admin.upload_quota.change", action="quota_change",
                channel="admin", method=request.method, status_code=302, request_id=request_id_for(request),
                resources=[{"type": "user", "id": quota.user_id, "ownerId": quota.user_id}],
                quota_changes={"before": before, "after": {"storageLimitMiB": quota.storage_limit_mib, "datasetLimit": quota.dataset_limit}},
            )
        formset.save_m2m()


@admin.register(DataSource)
class DataSourceAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "access_mode", "enabled", "last_success_at")
    list_filter = ("access_mode", "enabled")
    search_fields = ("name", "slug")
    readonly_fields = ("created_at", "updated_at", "last_preview_requested_at")


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
    readonly_fields = ("canonical_id",)


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


class MasterReadOnlyAdmin(admin.ModelAdmin):
    def get_readonly_fields(self, request, obj=None):
        return tuple(field.name for field in self.model._meta.fields)
    def has_add_permission(self, request): return False
    def has_delete_permission(self, request, obj=None): return False


@admin.register(CanonicalIdentifier)
class CanonicalIdentifierAdmin(MasterReadOnlyAdmin):
    list_display = ("namespace", "identifier", "entity_type", "taxon_key", "scope", "entity", "match_method")
    list_filter = ("entity_type", "namespace", "taxon_key")
    search_fields = ("identifier", "entity__label")


@admin.register(SourceEntityMapping)
class SourceEntityMappingAdmin(MasterReadOnlyAdmin):
    list_display = ("source_entity_id", "entity_type", "namespace", "taxon_key", "status", "entity", "source_release")
    list_filter = ("status", "entity_type", "source_release__source")
    search_fields = ("source_entity_id", "source_label", "entity__label")


@admin.register(SourceRecord)
class SourceRecordAdmin(MasterReadOnlyAdmin):
    list_display = ("source_record_id", "source_release", "status", "created_at")
    list_filter = ("status", "source_release__source")
    search_fields = ("source_record_id", "payload_sha256")


@admin.register(ResearchDataset)
class ResearchDatasetAdmin(SensitiveAdminAuditMixin, admin.ModelAdmin):
    list_display = ("name", "owner", "original_filename", "row_count", "byte_size", "created_at", "archived_at")
    list_filter = ("archived_at",)
    search_fields = ("name", "owner__username", "owner__email", "content_sha256")
    readonly_fields = tuple(field.name for field in ResearchDataset._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(ResearchDatasetAuditEvent)
class ResearchDatasetAuditEventAdmin(SensitiveAdminAuditMixin, admin.ModelAdmin):
    list_display = ("dataset", "owner", "actor", "action", "created_at")
    list_filter = ("action",)
    readonly_fields = tuple(field.name for field in ResearchDatasetAuditEvent._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(MedicalCase)
class MedicalCaseAdmin(SensitiveAdminAuditMixin, admin.ModelAdmin):
    list_display = ("title", "owner", "review_status", "updated_at", "archived_at")
    list_filter = ("review_status", "archived_at")
    search_fields = ("title", "owner__username", "owner__email")
    readonly_fields = tuple(field.name for field in MedicalCase._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(MedicalCaseAuditEvent)
class MedicalCaseAuditEventAdmin(SensitiveAdminAuditMixin, admin.ModelAdmin):
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
class MedicalCaseCandidateAdmin(SensitiveAdminAuditMixin, admin.ModelAdmin):
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
class VisualizationArtifactAdmin(SensitiveAdminAuditMixin, admin.ModelAdmin):
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
class AnalysisTaskAdmin(SensitiveAdminAuditMixin, admin.ModelAdmin):
    list_display = ("id", "task_type", "status", "owner", "created_by", "progress", "created_at")
    list_filter = ("task_type", "status")
    search_fields = ("owner__username", "owner__email")
    # Task records, including source versions, are written by the research
    # services and workers. Admin access must not rewrite their provenance.
    readonly_fields = tuple(
        field.name for field in (*AnalysisTask._meta.fields, *AnalysisTask._meta.many_to_many)
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(SensitiveAccessEvent)
class SensitiveAccessEventAdmin(admin.ModelAdmin):
    list_display = ("created_at", "actor", "operation", "action", "channel", "request_id")
    list_filter = ("action", "channel", "created_at")
    search_fields = ("actor__username", "operation", "request_id")
    readonly_fields = tuple(field.name for field in SensitiveAccessEvent._meta.fields)
    list_select_related = ("actor",)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(TargetIdentityMapping)
class TargetIdentityMappingAdmin(admin.ModelAdmin):
    list_display = ('entity', 'status', 'master', 'gene', 'match_method', 'reference_release')
    list_filter = ('status', 'reference_release')
    search_fields = ('entity__label', 'master__identifier', 'gene__identifier')
    list_select_related = ('entity', 'master', 'gene', 'reference_release__source')
    readonly_fields = tuple(field.name for field in TargetIdentityMapping._meta.fields)
    def has_add_permission(self, request): return False
    def has_change_permission(self, request, obj=None): return False
    def has_delete_permission(self, request, obj=None): return False


@admin.register(TargetMaster)
class TargetMasterAdmin(admin.ModelAdmin):
    list_display = ('key', 'label', 'namespace', 'taxon_key', 'symbol')
    list_filter = ('namespace', 'taxon_key')
    search_fields = ('key', 'identifier', 'label', 'symbol')
    readonly_fields = tuple(field.name for field in TargetMaster._meta.fields)
    def has_add_permission(self, request): return False
    def has_change_permission(self, request, obj=None): return False
    def has_delete_permission(self, request, obj=None): return False
