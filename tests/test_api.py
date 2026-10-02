from fastapi.testclient import TestClient

from backend.main import app


client = TestClient(app)


def test_health():
    res = client.get("/api/health")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"


def test_sources():
    res = client.get("/api/sources")
    assert res.status_code == 200
    assert len(res.json()["items"]) >= 5


def test_disease_search():
    res = client.get("/api/search/disease", params={"q": "Pulmonary fibrosis", "limit": 20})
    assert res.status_code == 200
    data = res.json()
    assert "herbs" in data
    assert "targets" in data


def test_herb_search():
    res = client.get("/api/search/herb", params={"q": "粳米", "limit": 20})
    assert res.status_code == 200
    assert "components" in res.json()


def test_intersection():
    res = client.post("/api/targets/intersection", json={"left": ["MAPK1", "AKT1"], "right": ["AKT1", "IL6"]})
    assert res.status_code == 200
    assert res.json()["intersection"] == ["AKT1"]


def test_compare():
    res = client.post("/api/components/compare", json={"detected": ["quercetin"], "reference": ["quercetin", "kaempferol"]})
    assert res.status_code == 200
    assert res.json()["match_rate"] == 100


def test_qwen_status():
    res = client.get("/api/qwen/status")
    assert res.status_code == 200
    data = res.json()
    assert data["mode"] == "OpenAI compatible chat/completions"
    assert data["env_key_name"] == "DASHSCOPE_API_KEY"
    assert "qwen-plus" in data["models"]
    assert data["biancang_model"] == "QLUNLP/BianCang-Qwen2.5-7B-Instruct"


def test_qwen_models():
    res = client.get("/api/qwen/models")
    assert res.status_code == 200
    data = res.json()
    assert data["default"] in data["items"]
    assert data["base_url"].startswith("https://")
    assert "QLUNLP/BianCang-Qwen2.5-7B-Instruct" in data["items"]
    assert any(preset["id"] == "biancang-local" for preset in data["presets"])


def test_qwen_invalid_base_url():
    res = client.post(
        "/api/qwen/test",
        json={"api_key": "test-key", "base_url": "not-a-url", "model": "qwen-plus"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["ok"] is False
    assert "Base URL" in data["error"]
