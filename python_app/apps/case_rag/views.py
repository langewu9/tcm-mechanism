from django.http import Http404
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from apps.core.services.access_audit import mark_sensitive_access
from .models import CaseCorpusDocument
from .services import active_release, corpus_summary, ranked_documents, serialize_document


class CorpusQuery(serializers.Serializer):
    q = serializers.CharField(max_length=160, required=False, allow_blank=True, default="")
    category = serializers.ChoiceField(choices=["", *CaseCorpusDocument.Category.values], required=False, default="")
    page = serializers.IntegerField(min_value=1, max_value=10000, default=1)


class CaseCorpusListView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(operation_id="case_corpus_list", parameters=[CorpusQuery], responses=OpenApiTypes.OBJECT)
    def get(self, request):
        query = CorpusQuery(data=request.query_params)
        query.is_valid(raise_exception=True)
        values = query.validated_data
        release = active_release()
        summary = corpus_summary(release)
        if not release:
            return Response({"summary": summary, "count": 0, "page": 1, "pageSize": 12, "results": []})
        documents, terms = ranked_documents(release, values["q"], values["category"])
        count = documents.count()
        page_size = 12
        start = (values["page"] - 1) * page_size
        page_documents = list(documents.select_related("release")[start:start + page_size])
        response = Response({"summary": summary, "count": count, "page": values["page"], "pageSize": page_size,
                             "results": [serialize_document(document, terms=terms) for document in page_documents]})
        mark_sensitive_access(
            request, operation="case_corpus.list", action="list",
            resources=({"type": "case_corpus_document", "id": document.pk,
                        "ownerId": None, "releaseId": release.pk} for document in page_documents),
        )
        return response


class CaseCorpusSummaryView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(operation_id="case_corpus_summary", responses=OpenApiTypes.OBJECT)
    def get(self, request):
        from apps.core.services.case_analysis import case_model_configuration
        return Response({**corpus_summary(), "modelConfiguration": case_model_configuration()})


class CaseCorpusDetailView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(operation_id="case_corpus_detail", responses=OpenApiTypes.OBJECT)
    def get(self, request, pk):
        release = active_release()
        document = CaseCorpusDocument.objects.using("case_rag").filter(release=release, pk=pk).select_related("release").first() if release else None
        if document is None:
            raise Http404
        response = Response(serialize_document(document, detail=True))
        mark_sensitive_access(
            request, operation="case_corpus.detail", action="view",
            resources=[{"type": "case_corpus_document", "id": document.pk,
                        "ownerId": None, "releaseId": document.release_id}],
        )
        return response
