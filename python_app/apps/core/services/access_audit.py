"""Collect bounded references; persist only after a successful response."""

from itertools import islice


MAX_ACCESS_REFERENCES = 250
RESOURCE_TYPES = {
    "dataset", "case", "task", "artifact", "case_candidate", "proteomics_row",
    "case_audit", "dataset_audit", "user", "case_corpus_document",
}
MODEL_RESOURCE_TYPES = {
    "core.researchdataset": "dataset", "core.medicalcase": "case",
    "core.analysistask": "task", "core.visualizationartifact": "artifact",
    "core.medicalcasecandidate": "case_candidate",
    "core.medicalcaseauditevent": "case_audit",
    "core.researchdatasetauditevent": "dataset_audit",
    "proteomics.proteomicsrowresult": "proteomics_row", "auth.user": "user",
}


def resource_reference(resource):
    if isinstance(resource, dict):
        kind = resource.get("type")
        reference = {key: resource.get(key) for key in ("type", "id", "ownerId")}
        if kind == "case_corpus_document":
            # Shared reference records have no researcher owner. Record the corpus
            # release separately so an audit remains attributable across updates.
            reference["releaseId"] = resource.get("releaseId")
    else:
        kind = MODEL_RESOURCE_TYPES.get(resource._meta.label_lower)
        owner_id = getattr(resource, "owner_id", None)
        if kind == "case_candidate":
            owner_id = resource.medical_case.owner_id
        elif kind == "proteomics_row":
            owner_id = resource.task.owner_id
        elif kind == "user":
            owner_id = resource.pk
        reference = {"type": kind, "id": resource.pk, "ownerId": owner_id}
    if reference["type"] not in RESOURCE_TYPES:
        raise ValueError("Unsupported audit resource type.")
    if type(reference["id"]) is not int or reference["id"] <= 0:
        raise ValueError("Audit references require a positive record ID.")
    if reference["type"] == "case_corpus_document":
        if reference["ownerId"] is not None:
            raise ValueError("Shared corpus audit references cannot have a user owner.")
        if type(reference["releaseId"]) is not int or reference["releaseId"] <= 0:
            raise ValueError("Shared corpus audit references require a positive release ID.")
    elif type(reference["ownerId"]) is not int or reference["ownerId"] <= 0:
        raise ValueError("Audit references require a positive owner ID.")
    return reference


def mark_sensitive_access(request, *, operation, action, resources):
    """Never copy filenames, clinical text, query strings, cookies or results."""
    request = getattr(request, "_request", request)
    references = [resource_reference(item) for item in islice(iter(resources), MAX_ACCESS_REFERENCES + 1)]
    request.sensitive_access = {
        "operation": operation, "action": action,
        "resources": references[:MAX_ACCESS_REFERENCES],
        "resources_truncated": len(references) > MAX_ACCESS_REFERENCES,
    }


class SensitiveReadAuditMixin:
    """Trace returned list records and permission-checked detail objects."""
    sensitive_resource_type = None

    def get_object(self):
        instance = super().get_object()
        self._sensitive_object = instance
        return instance

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        if request.method not in {"GET", "HEAD"} or not 200 <= response.status_code < 300:
            return response
        action = getattr(self, "action", "retrieve")
        if action in {"list", "summaries"}:
            rows = response.data.get("results", [])
            resources = ({"type": self.sensitive_resource_type, "id": row["id"], "ownerId": row["owner_id"]} for row in rows)
            audit_action = "list"
        elif hasattr(self, "_sensitive_object"):
            resources = [self._sensitive_object]
            audit_action = {"download": "download", "export": "export", "snapshot_export": "export"}.get(action, "view")
        else:
            return response
        mark_sensitive_access(request, operation=f"{self.sensitive_resource_type}.{action}", action=audit_action, resources=resources)
        return response


class SensitiveAdminAuditMixin:
    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        if self.model._meta.label_lower == "core.medicalcasecandidate":
            queryset = queryset.select_related("medical_case")
        elif self.model._meta.label_lower == "proteomics.proteomicsrowresult":
            queryset = queryset.select_related("task")
        return queryset

    def changelist_view(self, request, extra_context=None):
        response = super().changelist_view(request, extra_context)
        context = getattr(response, "context_data", None) or {}
        if request.method in {"GET", "HEAD"} and response.status_code == 200 and "cl" in context:
            mark_sensitive_access(request, operation=f"admin.{self.model._meta.model_name}.list", action="list", resources=context["cl"].result_list)
        return response

    def change_view(self, request, object_id, form_url="", extra_context=None):
        response = super().change_view(request, object_id, form_url, extra_context)
        context = getattr(response, "context_data", None) or {}
        if request.method in {"GET", "HEAD"} and response.status_code == 200 and context.get("original") is not None:
            mark_sensitive_access(request, operation=f"admin.{self.model._meta.model_name}.view", action="view", resources=[context["original"]])
        return response

    def history_view(self, request, object_id, extra_context=None):
        response = super().history_view(request, object_id, extra_context)
        context = getattr(response, "context_data", None) or {}
        if request.method in {"GET", "HEAD"} and response.status_code == 200 and context.get("object") is not None:
            mark_sensitive_access(request, operation=f"admin.{self.model._meta.model_name}.history", action="view", resources=[context["object"]])
        return response
