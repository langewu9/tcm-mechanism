from __future__ import annotations

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, Response

from . import chembl_service, data_service, qwen_service
from .config import FRONTEND_DIR
from .models import CompareRequest, IntersectionRequest, QwenTestRequest, ScientistRequest


app = FastAPI(title="中医药理数据库与可视化分析平台", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def api_health():
    info = data_service.health()
    info["chembl_available"] = chembl_service.available()
    info["qwen"] = qwen_service.status()
    return info


@app.get("/api/sources")
def api_sources():
    return {"items": data_service.sources()}


@app.get("/api/search/disease")
def api_search_disease(q: str = Query(..., min_length=1), limit: int = 100):
    return data_service.search_disease(q, limit)


@app.get("/api/search/herb")
def api_search_herb(q: str = Query(..., min_length=1), limit: int = 200):
    return data_service.search_herb(q, limit)


@app.get("/api/search/component")
def api_search_component(q: str = Query(..., min_length=1), limit: int = 200):
    return data_service.search_component(q, limit)


@app.post("/api/targets/intersection")
def api_intersection(payload: IntersectionRequest):
    return data_service.intersect_targets(payload.left, payload.right)


@app.post("/api/components/compare")
def api_compare(payload: CompareRequest):
    return data_service.compare_components(payload.detected, payload.reference)


@app.get("/api/chembl/molecules")
def api_chembl_molecules(q: str = Query(..., min_length=1), limit: int = 30):
    return chembl_service.search_molecules(q, limit)


@app.get("/api/chembl/activities")
def api_chembl_activities(chembl_id: str = Query(..., min_length=1), limit: int = 50):
    return chembl_service.molecule_activities(chembl_id, limit)


@app.post("/api/scientist/hypothesis")
def api_scientist_hypothesis(payload: ScientistRequest):
    report = data_service.scientist_hypothesis(payload.question, payload.disease, payload.formula, payload.focus)
    report["qwen_status"] = qwen_service.status()
    if payload.use_qwen:
        qwen_result = qwen_service.chat(
            qwen_service.scientific_plan_prompt(report),
            api_key=payload.qwen_api_key,
            base_url=payload.qwen_base_url,
            model=payload.qwen_model,
            temperature=0.2,
            max_tokens=1200,
            timeout=300,
        )
        report["qwen_result"] = qwen_result
        report["qwen_enhanced_text"] = qwen_result.get("content", "") if qwen_result.get("ok") else ""
    else:
        report["qwen_result"] = {"ok": False, "error": "未启用Qwen增强，当前为本地证据整合报告。"}
        report["qwen_enhanced_text"] = ""
    return report


@app.get("/api/qwen/status")
def api_qwen_status():
    return qwen_service.status()


@app.get("/api/qwen/models")
def api_qwen_models():
    return qwen_service.models()


@app.post("/api/qwen/test")
def api_qwen_test(payload: QwenTestRequest):
    return qwen_service.test_connection(payload.api_key, payload.base_url, payload.model)


if FRONTEND_DIR.exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIR / "assets"), name="assets")


@app.get("/")
def index():
    return FileResponse(FRONTEND_DIR / "index.html")


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    return Response(status_code=204)
