from django.contrib import admin

from .models import ProteomicsRowResult


@admin.register(ProteomicsRowResult)
class ProteomicsRowResultAdmin(admin.ModelAdmin):
    list_display = (
        "task",
        "row_index",
        "original_label",
        "normalized_symbol",
        "mapping_status",
        "selected",
    )
    list_filter = ("mapping_status", "selected")
    search_fields = ("original_label", "normalized_symbol", "task__owner__username")
    readonly_fields = [field.name for field in ProteomicsRowResult._meta.fields]

    def has_add_permission(self, request):
        return False

