"""Administrator-only diagnostics for integrations already present in main."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit

from django.conf import settings
from django.db import DatabaseError, connection
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from apps.core.models import DataSource
from apps.core.permissions import IsPlatformAdministrator
from apps.core.services.case_analysis import (
    MAX_MODEL_RESPONSE_BYTES,
    _NoRedirect,
    _is_local_or_private_host,
    case_model_configuration,
)
from apps.core.services.chembl import ChemblServiceError, search_molecules
from apps.core.services.component_names import compare_components_multilingual
from apps.core.services.disease_names import ALIAS_DATA, disease_entity_queryset, expand_disease_queries
from apps.core.services.herb_evidence import batch_herb_component_evidence
from apps.core.services.network_pharmacology import build_network_pharmacology
from config.runtime_logs import record_runtime_event


INTEGRATION_TARGETS = ("qwen", "disease", "herb", "component", "chembl", "intersection", "compare", "scientist")


class IntegrationTestRequestSerializer(serializers.Serializer):
    target = serializers.ChoiceField(choices=INTEGRATION_TARGETS)
    consent = serializers.BooleanField(required=False, default=False)


class IntegrationServiceStatusSerializer(serializers.Serializer):
    ok = serializers.BooleanField()
    status = serializers.IntegerField()
    url = serializers.CharField()
    data = serializers.JSONField(required=False)
    error = serializers.CharField(required=False)


class IntegrationServicesSerializer(serializers.Serializer):
    health = IntegrationServiceStatusSerializer()
    sources = IntegrationServiceStatusSerializer()
    qwenStatus = IntegrationServiceStatusSerializer()
    qwenModels = IntegrationServiceStatusSerializer()


class IntegrationStatusSerializer(serializers.Serializer):
    ok = serializers.BooleanField()
    checkedAt = serializers.DateTimeField()
    elapsedMs = serializers.IntegerField()
    services = IntegrationServicesSerializer()


class IntegrationTestResultSerializer(serializers.Serializer):
    ok = serializers.BooleanField()
    status = serializers.IntegerField()
    url = serializers.CharField()
    data = serializers.JSONField(required=False, allow_null=True)
    error = serializers.CharField(required=False, allow_null=True)
    elapsedMs = serializers.IntegerField()


class IntegrationTestResponseSerializer(serializers.Serializer):
    target = serializers.ChoiceField(choices=INTEGRATION_TARGETS)
    result = IntegrationTestResultSerializer()


def _result(*, ok: bool, status: int, url: str, data=None, error: str | None = None, started: float):
    return {
        "ok": ok,
        "status": status,
        "url": url,
        "data": data,
        "error": error,
        "elapsedMs": round((time.monotonic() - started) * 1000),
    }


class IntegrationStatusView(APIView):
    permission_classes = [IsPlatformAdministrator]

    @extend_schema(responses=IntegrationStatusSerializer)
    def get(self, request):
        started = time.monotonic()
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                cursor.fetchone()
            database_ok = True
        except DatabaseError:
            database_ok = False

        model = case_model_configuration()
        enabled_sources = DataSource.objects.filter(enabled=True).count() if database_ok else 0
        services = {
            "health": {
                "ok": database_ok,
                "status": 200 if database_ok else 503,
                "url": "/api/v1/health/",
                "data": {"api": "Django", "database": "ok" if database_ok else "不可用"},
            },
            "sources": {
                "ok": database_ok,
                "status": 200 if database_ok else 503,
                "url": "/api/v1/catalog/sources/",
                "data": {"enabledSources": enabled_sources},
            },
            "qwenStatus": {
                "ok": bool(model["configured"]),
                "status": 200 if model["configured"] else 503,
                "url": "平台配置的本机/内网模型",
                "data": model,
            },
            "qwenModels": {
                "ok": bool(model["configured"]),
                "status": 200 if model["configured"] else 503,
                "url": "平台配置的本机/内网模型",
                "data": {"models": [model["name"]] if model["configured"] else []},
            },
        }
        return Response({
            "ok": all(service["ok"] for service in services.values()),
            "checkedAt": timezone.now().isoformat(),
            "services": services,
            "elapsedMs": round((time.monotonic() - started) * 1000),
        })


def _test_model_connection():
    configuration = case_model_configuration()
    if not configuration["configured"]:
        return False, 503, None, "尚未配置受信任的本机/内网模型。"

    base_url = str(settings.CASE_MODEL_BASE_URL or "").strip().rstrip("/")
    parsed = urlsplit(base_url)
    if not parsed.hostname or not _is_local_or_private_host(parsed.hostname):
        return False, 400, None, "模型地址必须是受信任的本机或内网地址。"

    payload = {
        "model": configuration["name"],
        "temperature": 0,
        "max_tokens": 16,
        "messages": [
            {"role": "system", "content": "只回复 OK。"},
            {"role": "user", "content": "连接测试，请只回复 OK。"},
        ],
    }
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if settings.CASE_MODEL_API_KEY:
        headers["Authorization"] = f"Bearer {settings.CASE_MODEL_API_KEY}"
    request = urllib.request.Request(
        f"{base_url}/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect)
        with opener.open(request, timeout=min(max(settings.CASE_MODEL_TIMEOUT_SECONDS, 1), 20)) as response:
            raw = response.read(MAX_MODEL_RESPONSE_BYTES + 1)
            status_code = response.status
        if len(raw) > MAX_MODEL_RESPONSE_BYTES:
            return False, 502, None, "模型响应超过安全大小限制。"
        response_data = json.loads(raw.decode("utf-8"))
        content = response_data["choices"][0]["message"]["content"]
        if not isinstance(content, str) or not content.strip():
            raise ValueError("empty model response")
        return True, status_code, {
            "model": configuration["name"],
            "version": configuration["version"],
            "response": content[:80],
        }, None
    except urllib.error.HTTPError as exc:
        return False, exc.code, None, f"模型服务返回 HTTP {exc.code}。"
    except (urllib.error.URLError, TimeoutError, OSError, UnicodeDecodeError, json.JSONDecodeError, KeyError, IndexError, TypeError, ValueError):
        return False, 502, None, "模型服务连接失败或未返回有效响应。"


class IntegrationTestView(APIView):
    permission_classes = [IsPlatformAdministrator]

    def get_throttles(self):
        try:
            target = self.request.data.get("target")
        except (AttributeError, ValueError):
            target = None
        if target in {"qwen", "chembl"}:
            self.throttle_scope = "chembl"
            return [ScopedRateThrottle()]
        return []

    @extend_schema(request=IntegrationTestRequestSerializer, responses=IntegrationTestResponseSerializer)
    def post(self, request):
        serializer = IntegrationTestRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        target = serializer.validated_data["target"]
        consent = serializer.validated_data["consent"]
        started = time.monotonic()

        try:
            if target == "qwen":
                if not consent:
                    raise ValidationError({"consent": "请先同意发送一条不含研究数据的连接测试文本到已配置的本机/内网模型。"})
                ok, status_code, data, error = _test_model_connection()
                result = _result(ok=ok, status=status_code, url="本机/内网模型 /chat/completions", data=data, error=error, started=started)
            elif target == "disease":
                expanded = expand_disease_queries("Pulmonary fibrosis")
                queryset = disease_entity_queryset(expanded)
                match_count = queryset.count()
                matches = list(queryset[:10])
                result = _result(ok=True, status=200, url="/api/v1/catalog/diseases/alias-search/", data={
                    "query": "Pulmonary fibrosis",
                    "expandedQueries": expanded,
                    "aliasSource": ALIAS_DATA["source"],
                    "aliasSourceCommit": ALIAS_DATA["sourceCommit"],
                    "count": match_count,
                    "previewCount": len(matches),
                    "results": [{"label": item.label, "stableId": item.stable_id} for item in matches],
                }, started=started)
            elif target in {"herb", "component"}:
                query_type = "herb" if target == "herb" else "compound"
                query = "粳米" if target == "herb" else "quercetin"
                data = batch_herb_component_evidence(query_type=query_type, queries=[query])
                result = _result(ok=True, status=200, url="/api/v1/catalog/herb-evidence/batch/", data=data, started=started)
            elif target == "chembl":
                if not consent:
                    raise ValidationError({"consent": "请先同意将测试词 quercetin 发送到 ChEMBL 官方服务。"})
                data = search_molecules("quercetin")
                result = _result(ok=True, status=200, url="https://www.ebi.ac.uk/chembl/api/data/molecule/search", data=data, started=started)
            elif target == "intersection":
                data = build_network_pharmacology(
                    user=request.user,
                    herb_query="粳米",
                    disease_query="Pulmonary fibrosis",
                    row_limit=1000,
                    persist=False,
                )
                result = _result(ok=True, status=200, url="/api/v1/analysis/network-pharmacology/", data=data, started=started)
            elif target == "compare":
                data = compare_components_multilingual(
                    detected_values="quercetin, kaempferol, unknown sample",
                    reference_values="quercetin, kaempferol, beta-sitosterol",
                )
                result = _result(ok=True, status=200, url="/api/v1/analysis/component-compare/", data=data, started=started)
            else:
                from apps.core.models import AnalysisTask
                from apps.core.services.complete_evidence import _scientist_data, relation_limit
                report, _ = _scientist_data(AnalysisTask(owner=request.user, input_parameters={
                    "question": "本地证据汇总检查（非实验）", "disease": "肺纤维化", "herb": "粳米",
                    "formulaHerbs": ["粳米"], "focus": "本地接口检查", "useModel": False,
                }), relation_limit())
                result = _result(
                    ok=True, status=200, url="/api/v1/research/assistant/ (scientist_hypothesis)",
                    data={"algorithmVersion": report["algorithmVersion"], "results": report["results"],
                          "sources": report["references"], "uncertainties": report["uncertainties"],
                          "externalCalls": False, "taskCreated": False}, started=started,
                )
        except ChemblServiceError as exc:
            result = _result(ok=False, status=503, url="https://www.ebi.ac.uk/chembl/api/data/molecule/search", error=str(exc), started=started)
        except (ValueError, DatabaseError) as exc:
            record_runtime_event("integration.failed", request=request, exception=exc, status_code=503)
            result = _result(
                ok=False, status=503, url=f"/api/v1/admin/integrations/test/ ({target})",
                error="服务检查失败，请联系管理员并提供请求编号。", started=started,
            )

        return Response({"target": target, "result": result})
